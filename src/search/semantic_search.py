"""SQLite-backed semantic indexing and hybrid transcript retrieval."""
from __future__ import annotations

import hashlib
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
        self._sqlite_vec_checked = False
        self._sqlite_vec_module = None
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
    def _vector_table_name(model_name: str) -> str:
        digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:16]
        return f"semantic_vec_{digest}"

    def _load_vector_extension(self):
        """Load sqlite-vec once per connection; the core path stays optional."""
        if self._sqlite_vec_checked:
            return self._sqlite_vec_module
        self._sqlite_vec_checked = True
        try:
            import sqlite_vec
            self.connection.enable_load_extension(True)
            try:
                sqlite_vec.load(self.connection)
            finally:
                self.connection.enable_load_extension(False)
            self._sqlite_vec_module = sqlite_vec
            return self._sqlite_vec_module
        except (ImportError, AttributeError, sqlite3.Error, RuntimeError, OSError):
            return None

    def _ensure_vector_table(self, model_name: str, dimension: int):
        sqlite_vec = self._load_vector_extension()
        if sqlite_vec is None:
            return None

        table = self._vector_table_name(model_name)
        existing = self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if existing is not None and f"FLOAT[{dimension}]" not in (existing["sql"] or ""):
            self.connection.execute(f'DROP TABLE "{table}"')

        self.connection.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS "{table}" USING vec0(
                segment_id INTEGER PRIMARY KEY,
                video_id TEXT,
                embedding FLOAT[{dimension}] distance_metric=cosine
            )
            """
        )
        vector_count = self.connection.execute(
            f'SELECT COUNT(*) FROM "{table}"'
        ).fetchone()[0]
        source_count = self.connection.execute(
            "SELECT COUNT(*) FROM segment_embeddings WHERE model_name = ?",
            (model_name,),
        ).fetchone()[0]

        if vector_count != source_count:
            self.connection.execute(f'DELETE FROM "{table}"')
            rows = self.connection.execute(
                """
                SELECT segment_id, video_id, embedding_json
                FROM segment_embeddings
                WHERE model_name = ?
                ORDER BY segment_id
                """,
                (model_name,),
            ).fetchall()
            self.connection.executemany(
                f'INSERT INTO "{table}" (segment_id, video_id, embedding) VALUES (?, ?, ?)',
                [
                    (
                        row["segment_id"],
                        row["video_id"],
                        sqlite_vec.serialize_float32(
                            self._validate_vector(json.loads(row["embedding_json"]))
                        ),
                    )
                    for row in rows
                ],
            )
            self.connection.commit()
        return sqlite_vec, table

    def _invalidate_vector_table(self, model_name: str) -> None:
        """Drop a derived vector table after source embeddings are replaced."""
        sqlite_vec = self._load_vector_extension()
        if sqlite_vec is None:
            return
        table = self._vector_table_name(model_name)
        try:
            self.connection.execute(f'DROP TABLE IF EXISTS "{table}"')
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()

    def _vector_search(
        self,
        query_vector: Sequence[float],
        provider: EmbeddingProvider,
        limit: int,
        media_id: str | None,
        media_ids: list[str] | None,
        speaker: str | None,
    ) -> list[dict] | None:
        # vec0 supports exact equality metadata filters. Keep more complex
        # multi-media and speaker scopes on the established SQLite fallback.
        if speaker is not None or (media_ids is not None and len(media_ids) != 1):
            return None
        selected_media = media_id
        if media_ids:
            if selected_media is not None and selected_media != media_ids[0]:
                return []
            selected_media = media_ids[0]

        try:
            loaded = self._ensure_vector_table(provider.model_name, len(query_vector))
            if loaded is None:
                return None
            sqlite_vec, table = loaded
            sql = (
                f'SELECT segment_id, distance FROM "{table}" '
                "WHERE embedding MATCH ? AND k = ?"
            )
            params: list[object] = [
                sqlite_vec.serialize_float32(list(query_vector)),
                limit + 1,
            ]
            if selected_media is not None:
                sql += " AND video_id = ?"
                params.append(selected_media)

            matches = self.connection.execute(sql, params).fetchall()
            # If the cutoff falls inside a tie, use the exact heap path so
            # deterministic segment-id tie ordering remains unchanged.
            if len(matches) > limit and math.isclose(
                float(matches[limit - 1]["distance"]),
                float(matches[limit]["distance"]),
                rel_tol=0.0,
                abs_tol=1e-7,
            ):
                return None

            matches = sorted(
                matches[:limit],
                key=lambda row: (float(row["distance"]), int(row["segment_id"])),
            )
            if not matches:
                return []

            ids = [int(row["segment_id"]) for row in matches]
            placeholders = ",".join("?" for _ in ids)
            segment_rows = self.connection.execute(
                f"""
                SELECT id, video_id, start, end, original_text, speaker
                FROM segments
                WHERE id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            by_id = {int(row["id"]): dict(row) for row in segment_rows}
            distance_by_id = {
                int(row["segment_id"]): float(row["distance"]) for row in matches
            }
            results = []
            for segment_id in ids:
                result = by_id.get(segment_id)
                if result is None:
                    continue
                result["semantic_score"] = round(
                    max(-1.0, min(1.0, 1.0 - distance_by_id[segment_id])), 6
                )
                results.append(result)
            return results
        except (ImportError, AttributeError, sqlite3.Error, RuntimeError, OSError, ValueError):
            # Discard any partial derived-index rebuild before falling back.
            self.connection.rollback()
            # Extension availability, version, or virtual-table errors must
            # never disable semantic search: the exact SQLite heap path below
            # remains the compatibility fallback.
            return None

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
            # The vec0 table is a derived, optional acceleration structure.
            # Invalidate it after source changes; it is rebuilt lazily on the
            # next unfiltered or single-media semantic query.
            self._invalidate_vector_table(provider.model_name)
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
        vector_results = self._vector_search(
            query_vector,
            provider,
            limit,
            media_id,
            media_ids,
            speaker,
        )
        if vector_results is not None:
            return vector_results

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
