"""Persistent metadata and optional CLIP embeddings for video keyframes."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Sequence


class KeyframeSearchIndex:
    """Store timestamped keyframes and search them with a multimodal provider."""

    def __init__(self, database_path: str = "data/database/videos.db"):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS keyframes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_id TEXT NOT NULL,
                frame_index INTEGER NOT NULL,
                timestamp_seconds REAL NOT NULL,
                image_path TEXT NOT NULL,
                image_sha256 TEXT NOT NULL,
                UNIQUE(media_id, frame_index)
            )
            """
        )
        keyframe_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(keyframes)")
        }
        if "image_sha256" not in keyframe_columns:
            self.connection.execute(
                "ALTER TABLE keyframes ADD COLUMN image_sha256 TEXT NOT NULL DEFAULT ''"
            )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS keyframe_embeddings (
                keyframe_id INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                PRIMARY KEY(keyframe_id, model_name),
                FOREIGN KEY(keyframe_id) REFERENCES keyframes(id)
                    ON DELETE CASCADE
            )
            """
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_keyframes_media_time "
            "ON keyframes(media_id, timestamp_seconds)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_keyframe_embeddings_model "
            "ON keyframe_embeddings(model_name, keyframe_id)"
        )
        self.connection.commit()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_vector(vector: Sequence[float]) -> list[float]:
        if not isinstance(vector, (list, tuple)) or not vector:
            raise ValueError("Visual embedding must be a non-empty vector.")
        values = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("Visual embedding values must be numeric.")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("Visual embedding values must be finite.")
            values.append(number)
        return values

    def replace_media_keyframes(
        self,
        media_id: str,
        frame_paths: Sequence[str | Path | tuple[str | Path, float]],
        interval_seconds: float = 30,
    ) -> int:
        if not isinstance(media_id, str) or not media_id.strip():
            raise ValueError("Media ID cannot be empty.")
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (int, float)):
            raise TypeError("Frame interval must be numeric.")
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("Frame interval must be positive and finite.")
        if not isinstance(frame_paths, (list, tuple)):
            raise TypeError("Frame paths must be a list or tuple.")
        if not frame_paths:
            raise ValueError("At least one keyframe is required.")

        records = []
        previous_timestamp = -1.0
        for index, value in enumerate(frame_paths, start=1):
            if isinstance(value, tuple):
                if len(value) != 2:
                    raise ValueError("Timestamped keyframes must contain (path, timestamp).")
                path = Path(value[0])
                timestamp = value[1]
                if (
                    isinstance(timestamp, bool)
                    or not isinstance(timestamp, (int, float))
                    or not math.isfinite(timestamp)
                    or timestamp < 0
                    or timestamp <= previous_timestamp
                ):
                    raise ValueError("Keyframe timestamps must be finite, non-negative, and increasing.")
                previous_timestamp = float(timestamp)
            else:
                path = Path(value)
                timestamp = (index - 1) * float(interval_seconds)
            if not path.is_file():
                raise FileNotFoundError(f"Keyframe image not found: {path}")
            records.append((
                media_id,
                index,
                round(float(timestamp), 3),
                str(path.resolve()),
                self._file_sha256(path),
            ))

        current = self.connection.execute(
            """
            SELECT media_id, frame_index, timestamp_seconds, image_path, image_sha256
            FROM keyframes WHERE media_id = ? ORDER BY frame_index
            """,
            (media_id,),
        ).fetchall()
        if [
            (row["media_id"], row["frame_index"], row["timestamp_seconds"], row["image_path"], row["image_sha256"])
            for row in current
        ] == records:
            return len(records)

        try:
            old_ids = [
                row["id"]
                for row in self.connection.execute(
                    "SELECT id FROM keyframes WHERE media_id = ?", (media_id,)
                )
            ]
            if old_ids:
                placeholders = ",".join("?" for _ in old_ids)
                self.connection.execute(
                    f"DELETE FROM keyframe_embeddings WHERE keyframe_id IN ({placeholders})",
                    old_ids,
                )
            self.connection.execute("DELETE FROM keyframes WHERE media_id = ?", (media_id,))
            self.connection.executemany(
                """
                INSERT INTO keyframes
                    (media_id, frame_index, timestamp_seconds, image_path, image_sha256)
                VALUES (?, ?, ?, ?, ?)
                """,
                records,
            )
            self.connection.commit()
            return len(records)
        except Exception:
            self.connection.rollback()
            raise

    def get_media_keyframes(self, media_id: str) -> list[dict]:
        if not isinstance(media_id, str) or not media_id.strip():
            raise ValueError("Media ID cannot be empty.")
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT id, media_id, frame_index, timestamp_seconds, image_path, image_sha256
                FROM keyframes WHERE media_id = ? ORDER BY frame_index
                """,
                (media_id,),
            ).fetchall()
        ]

    def index_media(
        self,
        media_id: str,
        provider,
        batch_size: int = 16,
    ) -> int:
        if not isinstance(media_id, str) or not media_id.strip():
            raise ValueError("Media ID cannot be empty.")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("Batch size must be a positive integer.")

        rows = self.connection.execute(
            "SELECT id, image_path FROM keyframes WHERE media_id = ? ORDER BY frame_index",
            (media_id,),
        ).fetchall()
        if not rows:
            return 0

        existing = self.connection.execute(
            "SELECT embedding_json FROM keyframe_embeddings WHERE model_name = ? LIMIT 1",
            (provider.model_name,),
        ).fetchone()
        expected_dimension = (
            len(self._validate_vector(json.loads(existing["embedding_json"])))
            if existing else None
        )

        # Run image decoding and model inference before opening a write
        # transaction so a large model batch does not block archive writes.
        staged_records = []
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset:offset + batch_size]
            images = [Path(row["image_path"]) for row in batch]
            if any(not image.is_file() for image in images):
                missing = next(image for image in images if not image.is_file())
                raise FileNotFoundError(f"Keyframe image not found: {missing}")
            vectors = provider.embed_images(images)
            if len(vectors) != len(batch):
                raise ValueError("Visual provider returned an unexpected vector count.")
            for row, vector in zip(batch, vectors):
                values = self._validate_vector(vector)
                if expected_dimension is None:
                    expected_dimension = len(values)
                elif len(values) != expected_dimension:
                    raise ValueError("Visual embedding dimensions are inconsistent.")
                staged_records.append((
                    row["id"], provider.model_name,
                    json.dumps(values, separators=(",", ":")),
                ))

        try:
            self.connection.execute(
                """
                DELETE FROM keyframe_embeddings
                WHERE model_name = ? AND keyframe_id IN (
                    SELECT id FROM keyframes WHERE media_id = ?
                )
                """,
                (provider.model_name, media_id),
            )
            self.connection.executemany(
                """
                INSERT INTO keyframe_embeddings
                    (keyframe_id, model_name, embedding_json)
                VALUES (?, ?, ?)
                """,
                staged_records,
            )
            self.connection.commit()
            return len(rows)
        except Exception:
            self.connection.rollback()
            raise

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right):
            raise ValueError("Query and stored visual embedding dimensions do not match.")
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    def _search(self, query_vector, provider, limit: int, media_ids=None):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Limit must be a positive integer.")
        vector = self._validate_vector(query_vector)
        sql = """
            SELECT k.id, k.media_id, k.frame_index, k.timestamp_seconds,
                   k.image_path, e.embedding_json
            FROM keyframe_embeddings e
            JOIN keyframes k ON k.id = e.keyframe_id
            WHERE e.model_name = ?
        """
        params = [provider.model_name]
        if media_ids is not None:
            if not media_ids:
                return []
            sql += " AND k.media_id IN (" + ",".join("?" for _ in media_ids) + ")"
            params.extend(media_ids)

        ranked = []
        for row in self.connection.execute(sql, params):
            if not Path(row["image_path"]).is_file():
                continue
            stored = self._validate_vector(json.loads(row["embedding_json"]))
            score = self._cosine_similarity(vector, stored)
            ranked.append((score, -row["id"], {
                "keyframe_id": row["id"],
                "media_id": row["media_id"],
                "frame_index": row["frame_index"],
                "timestamp_seconds": row["timestamp_seconds"],
                "image_path": row["image_path"],
                "visual_score": round(score, 6),
            }))
        ranked.sort(key=lambda item: (-item[0], -item[1]))
        return [item[2] for item in ranked[:limit]]

    def search_text(self, query: str, provider, limit: int = 20, media_ids=None):
        if not isinstance(query, str) or not query.strip():
            return []
        return self._search(provider.embed_text(query), provider, limit, media_ids)

    def search_image(self, image_path: str | Path, provider, limit: int = 20, media_ids=None):
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Reference image not found: {path}")
        vectors = provider.embed_images([path])
        if len(vectors) != 1:
            raise ValueError("Visual provider must return exactly one reference-image vector.")
        return self._search(vectors[0], provider, limit, media_ids)

    def close(self):
        self.connection.close()
