"""Evaluate visual keyframe retrieval against human relevance judgments."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.search.keyframe_search import KeyframeSearchIndex
from src.search.visual_embedding_provider import SentenceTransformerVisualProvider
from src.search.visual_evaluation import evaluate_rankings


def load_dataset(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        raise ValueError("Visual evaluation dataset must contain a queries list.")
    cases = data["queries"]
    if not cases:
        raise ValueError("Visual evaluation dataset contains no queries.")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Visual query {index} must be an object.")
        has_text = isinstance(case.get("query"), str) and bool(case["query"].strip())
        has_image = isinstance(case.get("reference_image"), str) and bool(case["reference_image"].strip())
        if has_text == has_image:
            raise ValueError(
                f"Visual query {index} must contain exactly one of query or reference_image."
            )
        if not isinstance(case.get("relevant_frames"), list) or not case["relevant_frames"]:
            raise ValueError(
                f"Visual query {index} needs a non-empty relevant_frames list."
            )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/evaluation/visual_queries.json"),
    )
    parser.add_argument("--database", default="data/database/videos.db")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if isinstance(args.top_k, bool) or args.top_k <= 0:
        parser.error("--top-k must be a positive integer.")

    cases = load_dataset(args.dataset)
    for index, case in enumerate(cases):
        if case.get("reference_image"):
            reference_path = (args.dataset.parent / case["reference_image"]).resolve()
            if not reference_path.is_file():
                parser.error(
                    f"Reference image for query {index} was not found: {reference_path}"
                )
    provider = SentenceTransformerVisualProvider()
    index = KeyframeSearchIndex(args.database)
    try:
        rankings = []
        for case in cases:
            if case.get("query"):
                results = index.search_text(
                    case["query"], provider, limit=args.top_k
                )
            else:
                image_path = (args.dataset.parent / case["reference_image"]).resolve()
                results = index.search_image(
                    image_path, provider, limit=args.top_k
                )
            rankings.append(results)
    finally:
        index.close()

    report = {
        "database": args.database,
        "dataset": str(args.dataset),
        "top_k": args.top_k,
        **evaluate_rankings(cases, rankings, k=args.top_k),
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
