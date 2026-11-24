"""SQLite-backed semantic indexing and hybrid transcript retrieval."""
from __future__ import annotations

import heapq
import json
import math
import sqlite3
from pathlib import Path
from typing import Sequence

from src.search.embedding_provider import EmbeddingProvider


UNSPECIFIED_SPEAKER = "__UNSPECIFIED_SPEAKER__"


class SemanticSearchIndex:
    """Stores optional embeddings separately from the existing FTS5 index."""

    def __init__(self, database_path: str = "data/database/videos.db"):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS segment_embeddings (
                segment_id INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                PRIMARY KEY (segment_id, model_name),
                FOREIGN KEY (segment_id) REFERENCES segments(id)
                    ON DELETE CASCADE
            )
            """
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_segment_embeddings_model "
            "ON segment_embeddings(model_name, video_id)"
        )
        self.connection.commit()

    @staticmethod
    def _validate_vector(vector: Sequence[float]) -> list[float]:
        if not isinstance(vector, (list, tuple)) or not vector:
            raise ValueError("Embedding must be a non-empty numeric vector.")
        values = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("Embedding values must be numbers.")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("Embedding values must be finite.")
            values.append(number)
        return values

    def index_media(
        self,
        media_id: str,
        provider: EmbeddingProvider,
        batch_size: int = 64,
    ) -> int:
        if not isinstance(media_id, str) or not media_id.strip():
            raise ValueError("Media ID cannot be empty.")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("Batch size must be a positive integer.")

        rows = self.connection.execute(
            """
            SELECT id, original_text
            FROM segments
            WHERE video_id = ?
            ORDER BY id
            """,
            (media_id,),
        ).fetchall()

        indexed = 0
        expected_dimension = None
        try:
            self.connection.execute(
                "DELETE FROM segment_embeddings WHERE video_id = ? AND model_name = ?",
                (media_id, provider.model_name),
            )
            existing = self.connection.execute(
                """
                SELECT embedding_json
                FROM segment_embeddings
                WHERE model_name = ?
                LIMIT 1
                """,
                (provider.model_name,),
            ).fetchone()
            if existing is not None:
                expected_dimension = len(
                    self._validate_vector(json.loads(existing["embedding_json"]))
                )

            for offset in range(0, len(rows), batch_size):
                batch = rows[offset:offset + batch_size]
                texts = [row["original_text"] for row in batch]
                vectors = provider.embed_documents(texts)
                if len(vectors) != len(batch):
                    raise ValueError("Embedding provider returned an unexpected vector count.")

                records = []
                for row, vector in zip(batch, vectors):
                    values = self._validate_vector(vector)
                    if expected_dimension is None:
                        expected_dimension = len(values)
                    elif len(values) != expected_dimension:
                        raise ValueError(
                            "Embedding provider returned inconsistent vector dimensions."
                        )
                    records.append((
                        row["id"],
                        media_id,
                        provider.model_name,
                        json.dumps(values, separators=(",", ":")),
                    ))
                self.connection.executemany(
                    """
                    INSERT INTO segment_embeddings
                        (segment_id, video_id, model_name, embedding_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    records,
                )
                indexed += len(records)
            self.connection.commit()
            return indexed
        except Exception:
            self.connection.rollback()
            raise

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right):
            raise ValueError("Query and stored embedding dimensions do not match.")
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    def search(
        self,
        query: str,
        provider: EmbeddingProvider,
        limit: int = 20,
        media_id: str | None = None,
        media_ids: list[str] | None = None,
        speaker: str | None = None,
    ) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or media_ids == []:
            return []
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Limit must be a positive integer.")

        query_vector = self._validate_vector(provider.embed_query(query))
        sql = """
            SELECT s.id, s.video_id, s.start, s.end, s.original_text,
                   s.speaker, e.embedding_json
            FROM segment_embeddings e
            JOIN segments s ON s.id = e.segment_id
            WHERE e.model_name = ?
        """
        params: list[object] = [provider.model_name]
        if media_id is not None:
            sql += " AND e.video_id = ?"
            params.append(media_id)
        if media_ids is not None:
            sql += " AND e.video_id IN (" + ",".join("?" for _ in media_ids) + ")"
            params.extend(media_ids)
        if speaker == UNSPECIFIED_SPEAKER:
            sql += " AND (s.speaker IS NULL OR TRIM(s.speaker) = '')"
        elif speaker is not None:
            sql += " AND s.speaker = ?"
            params.append(speaker)

        # Keep only the best k candidates while streaming SQLite rows. The
        # previous implementation retained every embedding and result in
        # memory before sorting, which grew with the entire archive size.
        # This remains exact (O(n) scoring) while reducing ranking memory to O(k).
        best_results = []
        for row in self.connection.execute(sql, params):
            stored = self._validate_vector(json.loads(row["embedding_json"]))
            score = self._cosine_similarity(query_vector, stored)
            result = {
                key: row[key]
                for key in ("id", "video_id", "start", "end", "original_text", "speaker")
            }
            result["semantic_score"] = round(score, 6)
            candidate = (score, -row["id"], result)
            if len(best_results) < limit:
                heapq.heappush(best_results, candidate)
            elif candidate[:2] > best_results[0][:2]:
                heapq.heapreplace(best_results, candidate)

        best_results.sort(key=lambda item: (-item[0], -item[1]))
        return [item[2] for item in best_results]

    def close(self) -> None:
        self.connection.close()
