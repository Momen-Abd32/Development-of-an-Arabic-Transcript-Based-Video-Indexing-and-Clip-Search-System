"""SQLite-backed audit history for archive and processing changes."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    """Append-only event history stored alongside the processing queue."""

    def __init__(self, database_path: str | Path = "data/database/processing_queue.db"):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.database_path, timeout=10, isolation_level=None
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                occurred_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                details_json TEXT NOT NULL
            )
        """)
        self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_events_time
            ON audit_events(occurred_at DESC, event_id)
        """)
        self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_events_entity
            ON audit_events(entity_type, entity_id, occurred_at DESC)
        """)

    def close(self) -> None:
        self.connection.close()

    def record(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> dict:
        for name, value in (
            ("action", action),
            ("entity_type", entity_type),
            ("entity_id", entity_id),
            ("actor", actor),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name.replace('_', ' ').capitalize()} cannot be empty.")
        if details is not None and not isinstance(details, dict):
            raise TypeError("Audit details must be a dictionary or None.")
        try:
            serialized = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValueError("Audit details must be JSON serializable.") from error

        event = {
            "event_id": uuid.uuid4().hex,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "actor": actor.strip(),
            "action": action.strip(),
            "entity_type": entity_type.strip(),
            "entity_id": entity_id.strip(),
            "details": json.loads(serialized),
        }
        self.connection.execute(
            """
            INSERT INTO audit_events (
                event_id, occurred_at, actor, action, entity_type, entity_id, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"], event["occurred_at"], event["actor"],
                event["action"], event["entity_type"], event["entity_id"], serialized,
            ),
        )
        return event

    def list_events(
        self,
        limit: int = 100,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor: str | None = None,
    ) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Limit must be a positive integer.")
        clauses = []
        parameters: list[Any] = []
        for column, value in (
            ("entity_type", entity_type),
            ("entity_id", entity_id),
            ("actor", actor),
        ):
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{column.replace('_', ' ').capitalize()} filter cannot be empty.")
                clauses.append(f"{column} = ?")
                parameters.append(value.strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"""
            SELECT * FROM audit_events {where}
            ORDER BY occurred_at DESC, event_id DESC LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            events.append(item)
        return events
