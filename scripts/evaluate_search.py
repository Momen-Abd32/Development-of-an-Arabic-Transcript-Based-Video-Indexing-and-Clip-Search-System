"""Evaluate transcript-search rankings against human relevance judgments."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.search.evaluation import evaluate_rankings
from src.search.search_engine import SearchEngine


def load_dataset(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        raise ValueError("Evaluation dataset must contain a queries list.")
    queries = data["queries"]
    for index, case in enumerate(queries):
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("query"), str)
            or not case["query"].strip()
            or not isinstance(case.get("relevant_segments"), list)
            or not case["relevant_segments"]
        ):
            raise ValueError(
                f"Evaluation query {index} needs query text and relevant_segments."
            )
    if not queries:
        raise ValueError("Evaluation dataset contains no judged queries.")
    return queries


def collect_rankings(engine, cases, mode, top_k, provider=None):
    """Run one retrieval mode so each ranker can be evaluated independently."""
    if mode in ("semantic", "hybrid") and provider is None:
        raise ValueError("A semantic embedding provider is required.")
    if mode == "semantic":
        return [engine.semantic_search(case["query"], provider, limit=top_k) for case in cases]
    if mode == "hybrid":
        return [engine.hybrid_search(case["query"], provider, limit=top_k) for case in cases]
    if mode == "fuzzy":
        return [engine.fuzzy_search(case["query"], limit=top_k) for case in cases]
    if mode == "exact":
        return [engine.exact_search(case["query"], limit=top_k) for case in cases]
    raise ValueError("Unsupported search mode: " + mode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/evaluation/search_queries.json"),
        help="JSON file containing human-judged relevance labels.",
    )
    parser.add_argument(
        "--mode",
        choices=("exact", "fuzzy", "semantic", "hybrid"),
        default="exact",
    )
    parser.add_argument("--database", default="data/database/videos.db")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--build-semantic-index",
        action="store_true",
        help="Build/refresh embeddings for all indexed media before semantic or hybrid evaluation.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if isinstance(args.top_k, bool) or args.top_k <= 0:
        parser.error("--top-k must be a positive integer.")
    cases = load_dataset(args.dataset)

    engine = SearchEngine(args.database)
    try:
        provider = None
        if args.mode in ("semantic", "hybrid"):
            from src.search.embedding_provider import SentenceTransformerProvider

            provider = SentenceTransformerProvider()
            if args.build_semantic_index:
                media_ids = [
                    row["video_id"]
                    for row in engine.db.connection.execute(
                        "SELECT DISTINCT video_id FROM segments ORDER BY video_id"
                    ).fetchall()
                ]
                for media_id in media_ids:
                    engine.index_semantic_media(media_id, provider)
        rankings = collect_rankings(engine, cases, args.mode, args.top_k, provider)
    finally:
        engine.close()

    report = {
        "mode": args.mode,
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
