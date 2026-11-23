"""Timestamped archive notes with an append-only audit trail."""
from __future__ import annotations

import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.media.audit_log import AuditLog


class ArchiveNotes:
    """Store review notes against media timestamps in the archive database."""

    MEDIA_ID_PATTERN = re.compile(r"[0-9a-f]{64}")
    NOTE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
    MAX_TEXT_LENGTH = 5000
    MAX_AUTHOR_LENGTH = 120

    def __init__(
        self,
        database_path: str | Path = "data/database/processing_queue.db",
    ):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.database_path,
            timeout=10,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS archive_notes (
                note_id TEXT PRIMARY KEY,
                media_id TEXT NOT NULL,
                timestamp_seconds REAL NOT NULL,
                note_text TEXT NOT NULL,
                author TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                CHECK(timestamp_seconds >= 0),
                CHECK(length(note_text) BETWEEN 1 AND 5000)
            )
        """)
        self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_archive_notes_media_time
            ON archive_notes(media_id, timestamp_seconds, created_at)
        """)

    def close(self) -> None:
        self.connection.close()

    @classmethod
    def _validate_media_id(cls, media_id: str) -> str:
        if not isinstance(media_id, str) or not cls.MEDIA_ID_PATTERN.fullmatch(media_id):
            raise ValueError("Media ID must be a lowercase SHA-256 hash.")
        return media_id

    @staticmethod
    def _validate_timestamp(timestamp_seconds: float) -> float:
        if isinstance(timestamp_seconds, bool) or not isinstance(
            timestamp_seconds, (int, float)
        ):
            raise TypeError("Timestamp must be a number.")
        value = float(timestamp_seconds)
        if not math.isfinite(value) or value < 0:
            raise ValueError("Timestamp must be finite and non-negative.")
        return value

    @classmethod
    def _validate_text(cls, note_text: str) -> str:
        if not isinstance(note_text, str):
            raise TypeError("Note text must be a string.")
        value = note_text.strip()
        if not value:
            raise ValueError("Note text cannot be empty.")
        if len(value) > cls.MAX_TEXT_LENGTH:
            raise ValueError(
                f"Note text cannot exceed {cls.MAX_TEXT_LENGTH} characters."
            )
        return value

    @classmethod
    def _validate_author(cls, author: str, field_name: str = "Author") -> str:
        if not isinstance(author, str) or not author.strip():
            raise ValueError(f"{field_name} cannot be empty.")
        value = author.strip()
        if len(value) > cls.MAX_AUTHOR_LENGTH:
            raise ValueError(
                f"{field_name} cannot exceed {cls.MAX_AUTHOR_LENGTH} characters."
            )
        return value

    @classmethod
    def _validate_note_id(cls, note_id: str) -> str:
        if not isinstance(note_id, str) or not cls.NOTE_ID_PATTERN.fullmatch(note_id):
            raise ValueError("Note ID is invalid.")
        return note_id

    def _record_audit(
        self,
        action: str,
        note: dict,
        actor: str,
        before: dict | None = None,
    ) -> None:
        audit = AuditLog(self.database_path)
        try:
            audit.record(
                action=action,
                entity_type="media_note",
                entity_id=note["note_id"],
                actor=actor,
                details={
                    "media_id": note["media_id"],
                    "timestamp_seconds": note["timestamp_seconds"],
                    "text_length": len(note["note_text"]),
                    "before": before,
                },
            )
        finally:
            audit.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return dict(row)

    def add_note(
        self,
        media_id: str,
        timestamp_seconds: float,
        note_text: str,
        author: str = "local_user",
    ) -> dict:
        media_id = self._validate_media_id(media_id)
        timestamp = self._validate_timestamp(timestamp_seconds)
        text = self._validate_text(note_text)
        author = self._validate_author(author)
        now = datetime.now(timezone.utc).isoformat()
        note = {
            "note_id": uuid.uuid4().hex,
            "media_id": media_id,
            "timestamp_seconds": timestamp,
            "note_text": text,
            "author": author,
            "created_at": now,
            "updated_at": now,
            "updated_by": author,
        }
        self.connection.execute(
            """
            INSERT INTO archive_notes (
                note_id, media_id, timestamp_seconds, note_text, author,
                created_at, updated_at, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note["note_id"], note["media_id"], note["timestamp_seconds"],
                note["note_text"], note["author"], note["created_at"],
                note["updated_at"], note["updated_by"],
            ),
        )
        self._record_audit("note_created", note, actor=author)
        return note

    def list_notes(self, media_id: str, limit: int = 200) -> list[dict]:
        media_id = self._validate_media_id(media_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Limit must be a positive integer.")
        rows = self.connection.execute(
            """
            SELECT * FROM archive_notes
            WHERE media_id = ?
            ORDER BY timestamp_seconds, created_at, note_id
            LIMIT ?
            """,
            (media_id, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_note(
        self,
        note_id: str,
        *,
        timestamp_seconds: float | None = None,
        note_text: str | None = None,
        updated_by: str = "local_user",
    ) -> dict:
        note_id = self._validate_note_id(note_id)
        updated_by = self._validate_author(updated_by, "Updated by")
        before_row = self.connection.execute(
            "SELECT * FROM archive_notes WHERE note_id = ?",
            (note_id,),
        ).fetchone()
        if before_row is None:
            raise KeyError(f"Archive note not found: {note_id}")
        before = self._row_to_dict(before_row)

        if timestamp_seconds is None and note_text is None:
            raise ValueError("At least one note field must be supplied.")
        timestamp = (
            before["timestamp_seconds"]
            if timestamp_seconds is None
            else self._validate_timestamp(timestamp_seconds)
        )
        text = (
            before["note_text"]
            if note_text is None
            else self._validate_text(note_text)
        )
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """
            UPDATE archive_notes
            SET timestamp_seconds = ?, note_text = ?, updated_at = ?, updated_by = ?
            WHERE note_id = ?
            """,
            (timestamp, text, now, updated_by, note_id),
        )
        updated = {
            **before,
            "timestamp_seconds": timestamp,
            "note_text": text,
            "updated_at": now,
            "updated_by": updated_by,
        }
        self._record_audit("note_updated", updated, actor=updated_by, before={
            "timestamp_seconds": before["timestamp_seconds"],
            "text_length": len(before["note_text"]),
        })
        return updated

    def delete_note(self, note_id: str, actor: str = "local_user") -> bool:
        note_id = self._validate_note_id(note_id)
        actor = self._validate_author(actor)
        row = self.connection.execute(
            "SELECT * FROM archive_notes WHERE note_id = ?",
            (note_id,),
        ).fetchone()
        if row is None:
            return False
        note = self._row_to_dict(row)
        self.connection.execute(
            "DELETE FROM archive_notes WHERE note_id = ?",
            (note_id,),
        )
        self._record_audit("note_deleted", note, actor=actor)
        return True
