"""Benchmark optional sqlite-vec KNN retrieval against the exact heap fallback.

Uses deterministic synthetic embeddings and never downloads an embedding model.
Run after installing requirements.txt and requirements-vector.txt:
    python scripts/benchmark_semantic_search.py --segments 10000 --dimension 64
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import tempfile
import time
from pathlib import Path

from src.search.semantic_search import SemanticSearchIndex


class SyntheticEmbeddingProvider:
    model_name = "synthetic-benchmark-v1"

    def __init__(self, dimension: int, seed: int):
        self.dimension = dimension
        self.seed = seed

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(
            f"{self.seed}:{text}".encode("utf-8")
        ).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        values = [rng.uniform(-1.0, 1.0) for _ in range(self.dimension)]
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(f"query:{text}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(f"document:{text}") for text in texts]


def build_database(database_path: Path, count: int) -> None:
    import sqlite3

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE segments (
                id INTEGER PRIMARY KEY,
                video_id TEXT NOT NULL,
                start REAL NOT NULL,
                end REAL NOT NULL,
                original_text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                speaker TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO segments
                (id, video_id, start, end, original_text, normalized_text, speaker)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    index,
                    f"media-{index % 20:02d}",
                    float(index * 5),
                    float(index * 5 + 4),
                    f"synthetic transcript segment {index}",
                    f"synthetic transcript segment {index}",
                    None,
                )
                for index in range(1, count + 1)
            ],
        )
        connection.commit()
    finally:
        connection.close()


def median_latency_ms(index, provider, query_count: int, top_k: int):
    samples = []
    results = []
    for query_number in range(query_count):
        query = f"benchmark query {query_number}"
        started = time.perf_counter()
        matches = index.search(query, provider, limit=top_k)
        samples.append((time.perf_counter() - started) * 1000.0)
        results.append(matches)
    return statistics.median(samples), results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segments", type=int, default=10000)
    parser.add_argument("--dimension", type=int, default=64)
    parser.add_argument("--queries", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    if min(args.segments, args.dimension, args.queries, args.top_k) <= 0:
        parser.error("segments, dimension, queries, and top-k must be positive")

    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        parser.error(
            "sqlite-vec is optional; install it with "
            "'pip install -r requirements-vector.txt'"
        )

    with tempfile.TemporaryDirectory(prefix="semantic-search-benchmark-") as temp:
        database_path = Path(temp) / "benchmark.db"
        build_database(database_path, args.segments)
        provider = SyntheticEmbeddingProvider(args.dimension, args.seed)

        vector_index = SemanticSearchIndex(str(database_path))
        fallback_index = SemanticSearchIndex(str(database_path))
        # Explicitly disable the extension only on the baseline connection.
        fallback_index._sqlite_vec_checked = True
        fallback_index._sqlite_vec_module = None

        try:
            indexed = vector_index.index_media("media-00", provider)
            # Index the rest of the archive as separate media items.
            for media_number in range(1, 20):
                indexed += vector_index.index_media(
                    f"media-{media_number:02d}", provider
                )

            # First query creates/backfills the derived vec0 table; exclude
            # that one-time build cost from steady-state query measurements.
            vector_index.search("warmup", provider, limit=args.top_k)
            vector_latency, vector_results = median_latency_ms(
                vector_index, provider, args.queries, args.top_k
            )
            fallback_latency, fallback_results = median_latency_ms(
                fallback_index, provider, args.queries, args.top_k
            )

            ids_match = all(
                [item["id"] for item in left] == [item["id"] for item in right]
                for left, right in zip(vector_results, fallback_results)
            )
            score_deltas = [
                abs(left_item["semantic_score"] - right_item["semantic_score"])
                for left, right in zip(vector_results, fallback_results)
                for left_item, right_item in zip(left, right)
            ]
            report = {
                "segments_indexed": indexed,
                "embedding_dimension": args.dimension,
                "queries": args.queries,
                "top_k": args.top_k,
                "sqlite_vec_median_ms": round(vector_latency, 3),
                "exact_heap_median_ms": round(fallback_latency, 3),
                "observed_speedup": round(
                    fallback_latency / vector_latency, 3
                ) if vector_latency else None,
                "top_k_ids_match": ids_match,
                "max_absolute_score_delta": round(max(score_deltas, default=0.0), 7),
                "note": (
                    "Synthetic local benchmark only; not a Dukkan Media quality "
                    "or production-scale performance claim."
                ),
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            vector_index.close()
            fallback_index.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
