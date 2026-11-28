"""Import prepared SADA 2022 transcript annotations and their source audio.

SADA CSV rows are timestamped segments, not standalone transcript files. This
importer groups rows by FileName, copies each selected WAV into the local
archive, saves its supplied annotations, and indexes them without running
Whisper.
"""
from __future__ import annotations

import csv
import hashlib
import math
import os
import shutil
import tempfile
from collections import OrderedDict
from pathlib import Path

from src.indexing.indexer import TranscriptIndexer
from src.media.media_catalog import MediaCatalog
from src.transcription.transcript_manager import TranscriptManager


SPLITS = {"train", "valid", "test"}


def _safe_dataset_path(root: Path, relative_name: str) -> Path:
    relative = Path(relative_name.replace("\\", "/"))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"Unsafe SADA FileName: {relative_name!r}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"SADA file is outside dataset directory: {relative_name}") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source: Path, destination: Path, digest: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and _sha256(destination) == digest:
        return
    if source.resolve() == destination.resolve():
        return

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        if _sha256(temporary) != digest:
            raise RuntimeError(f"SHA-256 mismatch while copying {source}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _first_episodes(csv_path: Path, limit: int | None) -> list[str]:
    selected: OrderedDict[str, None] = OrderedDict()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "FileName" not in reader.fieldnames:
            raise ValueError("SADA CSV must contain a FileName column.")
        for row in reader:
            name = (row.get("FileName") or "").strip()
            if name:
                selected.setdefault(name, None)
                if limit is not None and len(selected) >= limit:
                    break
    return list(selected)


def _segments_for_episodes(csv_path: Path, selected: set[str]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {name: [] for name in selected}
    required = ("SegmentStart", "SegmentEnd")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or ())
        missing = set(required) - fields
        if missing:
            raise ValueError(f"SADA CSV is missing columns: {', '.join(sorted(missing))}")
        if not ({"GroundTruthText", "ProcessedText"} & fields):
            raise ValueError("SADA CSV must contain GroundTruthText or ProcessedText.")

        for row in reader:
            file_name = (row.get("FileName") or "").strip()
            if file_name not in selected:
                continue
            raw_text = (row.get("GroundTruthText") or "").strip()
            if not raw_text:
                raw_text = (row.get("ProcessedText") or "").strip()
            if not raw_text:
                continue
            try:
                start = float(row["SegmentStart"])
                end = float(row["SegmentEnd"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid timestamps in SADA row for {file_name}") from exc
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError(f"Invalid segment range {start}-{end} in {file_name}")

            speaker = (row.get("Speaker") or "").strip() or None
            grouped[file_name].append({
                "start": start,
                "end": end,
                "text": raw_text,
                "speaker": speaker,
            })

    for name, segments in grouped.items():
        segments.sort(key=lambda item: (item["start"], item["end"]))
        if not segments:
            raise ValueError(f"No usable transcript segments found for {name}")
    return grouped


class SadaDatasetImporter:
    def __init__(
        self,
        dataset_dir: str = "data/external/sada2022",
        split: str = "train",
        max_episodes: int | None = 3,
        audio_source_dir: str = "data/audio/originals",
        transcript_dir: str = "data/transcripts",
        database_path: str = "data/database/videos.db",
        catalog_path: str = "data/database/media_catalog.json",
    ):
        if split not in SPLITS:
            raise ValueError(f"split must be one of: {', '.join(sorted(SPLITS))}")
        if max_episodes is not None and max_episodes < 1:
            raise ValueError("max_episodes must be at least 1 or None")
        self.dataset_dir = Path(dataset_dir)
        self.split = split
        self.max_episodes = max_episodes
        self.audio_source_dir = Path(audio_source_dir)
        self.transcript_dir = Path(transcript_dir)
        self.database_path = database_path
        self.catalog = MediaCatalog(catalog_path)

    def import_dataset(self, dry_run: bool = False) -> list[dict]:
        csv_path = self.dataset_dir / f"{self.split}.csv"
        if not csv_path.is_file():
            raise FileNotFoundError(f"SADA split CSV not found: {csv_path}")

        episode_names = _first_episodes(csv_path, self.max_episodes)
        if not episode_names:
            raise ValueError(f"No episode rows found in {csv_path}")
        grouped = _segments_for_episodes(csv_path, set(episode_names))

        results = []
        for relative_name in episode_names:
            source = _safe_dataset_path(self.dataset_dir, relative_name)
            if not source.is_file():
                results.append({
                    "file": relative_name,
                    "status": "missing_audio",
                    "segments": len(grouped[relative_name]),
                })
                continue

            segments = grouped[relative_name]
            if dry_run:
                results.append({
                    "file": relative_name,
                    "status": "ready",
                    "segments": len(segments),
                    "audio_bytes": source.stat().st_size,
                })
                continue

            media_id = _sha256(source)
            destination = self.audio_source_dir / f"{media_id}{source.suffix.lower()}"
            transcript_path = self.transcript_dir / f"{media_id}.json"
            registered = False
            try:
                _copy_verified(source, destination, media_id)
                self.catalog.register_media(
                    media_id=media_id,
                    media_type="audio",
                    source_name=f"SADA2022/{relative_name}",
                    stored_path=str(destination),
                    status="processing",
                )
                registered = True

                TranscriptManager.save(segments, str(transcript_path))
                indexer = TranscriptIndexer(self.database_path)
                try:
                    indexed = indexer.index_segments(media_id, segments)
                finally:
                    indexer.close()

                self.catalog.update_status(media_id, "transcribed")
                tags = ["SADA2022", f"split:{self.split}"]
                self.catalog.update_archive_metadata(
                    media_id,
                    collection="SADA 2022",
                    tags=tags,
                )
                results.append({
                    "file": relative_name,
                    "media_id": media_id,
                    "status": "imported",
                    "segments": indexed,
                    "audio_path": str(destination),
                    "transcript_path": str(transcript_path),
                })
            except Exception as exc:
                if registered:
                    try:
                        self.catalog.update_status(media_id, "failed", str(exc))
                    except Exception:
                        pass
                results.append({
                    "file": relative_name,
                    "media_id": media_id,
                    "status": "failed",
                    "segments": len(segments),
                    "error": str(exc),
                })
        return results
