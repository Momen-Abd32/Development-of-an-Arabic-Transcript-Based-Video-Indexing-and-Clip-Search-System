"""Download a small, reproducible SADA 2022 sample from Kaggle.

Requires the Kaggle CLI and configured Kaggle API credentials. It downloads
only one split CSV and the WAV episodes referenced by the first N CSV entries.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.media.sada_dataset_importer import SadaDatasetImporter


DATASET = "sdaiancai/sada2022"


def _download_file(file_name: str, destination: Path) -> None:
    command = [
        "kaggle", "datasets", "download", "-d", DATASET,
        "-f", file_name, "-p", str(destination), "--unzip",
    ]
    subprocess.run(command, check=True)


def _first_files(csv_path: Path, limit: int) -> list[str]:
    selected = []
    seen = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if "FileName" not in (reader.fieldnames or []):
            raise ValueError("SADA CSV does not contain FileName.")
        for row in reader:
            name = (row.get("FileName") or "").strip().replace("\\", "/")
            if name and name not in seen:
                parts = Path(name).parts
                if Path(name).is_absolute() or ".." in parts:
                    raise ValueError(f"Unsafe path in SADA CSV: {name}")
                selected.append(name)
                seen.add(name)
                if len(selected) >= limit:
                    break
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download and import a small SADA 2022 Arabic audio/transcript sample."
    )
    parser.add_argument("--split", choices=("train", "valid", "test"), default="train")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--dataset-dir", default="data/external/sada2022")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.episodes < 1:
        parser.error("--episodes must be at least 1")

    dataset_dir = Path(args.dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    csv_path = dataset_dir / f"{args.split}.csv"
    if not csv_path.exists():
        _download_file(f"{args.split}.csv", dataset_dir)

    files = _first_files(csv_path, args.episodes)
    print(f"Selected {len(files)} SADA episodes from {args.split}.csv")
    if args.dry_run:
        for name in files:
            print(f"[PLAN] {name}")
        print("Dry run: no episode audio was downloaded or imported.")
        return 0

    for name in files:
        target = dataset_dir / name
        if target.exists():
            print(f"[EXISTS] {name}")
            continue
        print(f"[DOWNLOAD] {name}")
        _download_file(name, dataset_dir)
        if not target.exists():
            matches = list(dataset_dir.rglob(Path(name).name))
            if len(matches) == 1:
                target.parent.mkdir(parents=True, exist_ok=True)
                target = matches[0]
            else:
                raise FileNotFoundError(
                    f"Kaggle download completed but {name} was not found under {dataset_dir}"
                )

    importer = SadaDatasetImporter(
        dataset_dir=str(dataset_dir),
        split=args.split,
        max_episodes=args.episodes,
    )
    results = importer.import_dataset()
    for item in results:
        print(f"[{item['status'].upper()}] {item['file']} — {item['segments']} segments")
        if item.get("error"):
            print(f"  {item['error']}")
    imported = sum(item["status"] == "imported" for item in results)
    print(f"\nImported: {imported} / {len(results)} episodes")
    return 0 if all(item["status"] in {"imported", "ready"} for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
