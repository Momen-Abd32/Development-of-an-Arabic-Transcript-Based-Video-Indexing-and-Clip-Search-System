"""Evaluate fused transcript and visual retrieval using human relevance labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.search.cross_modal_evaluation import evaluate_rankings
from src.search.cross_modal_search import CrossModalSearch
from src.search.keyframe_search import KeyframeSearchIndex
from src.search.search_engine import SearchEngine
from src.search.visual_embedding_provider import SentenceTransformerVisualProvider


def load_dataset(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        raise ValueError("Cross-modal evaluation dataset must contain a queries list.")
    cases = data["queries"]
    if not cases:
        raise ValueError("Cross-modal evaluation dataset contains no queries.")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Cross-modal query {index} must be an object.")
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"Cross-modal query {index} needs a non-empty query.")
        if not isinstance(case.get("relevant_results"), list) or not case["relevant_results"]:
            raise ValueError(
                f"Cross-modal query {index} needs a non-empty relevant_results list."
            )
    evaluate_rankings(cases, [[] for _ in cases], k=1)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/evaluation/cross_modal_queries.json"),
    )
    parser.add_argument("--database", default="data/database/videos.db")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if isinstance(args.top_k, bool) or args.top_k <= 0:
        parser.error("--top-k must be a positive integer.")

    cases = load_dataset(args.dataset)
    provider = SentenceTransformerVisualProvider()
    engine = SearchEngine(args.database)
    visual_index = None
    try:
        visual_index = KeyframeSearchIndex(args.database)
        cross_modal = CrossModalSearch(engine, visual_index)
        rankings = [
            cross_modal.search_text(
                case["query"],
                limit=args.top_k,
                visual_provider=provider,
                include_visual=True,
            )
            for case in cases
        ]
    finally:
        if visual_index is not None:
            visual_index.close()
        engine.close()

    report = {
        "database": args.database,
        "dataset": str(args.dataset),
        "visual_model": provider.model_name,
        "ranking_method": "reciprocal_rank_fusion",
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
