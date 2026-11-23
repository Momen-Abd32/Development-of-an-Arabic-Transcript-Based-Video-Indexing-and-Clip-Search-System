"""Durable SQLite-backed processing queue with retries and crash recovery."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.media.audit_log import AuditLog


STATUSES = {"queued", "running", "completed", "failed", "cancelled"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat()


class ProcessingQueue:
    """Persist batch-processing jobs independently from transcript/search data."""

    def __init__(self, database_path: str | Path = "data/database/processing_queue.db"):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.database_path,
            timeout=10,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS processing_jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('queued', 'running', 'completed', 'failed', 'cancelled')
                ),
                progress REAL NOT NULL DEFAULT 0 CHECK (
                    progress >= 0 AND progress <= 100
                ),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                locked_at TEXT,
                error TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1))
            )
        """)
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(processing_jobs)")
        }
        if "cancel_requested" not in columns:
            self.connection.execute(
                "ALTER TABLE processing_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"
            )
        self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_processing_jobs_status_created
            ON processing_jobs(status, created_at)
        """)
        self.audit_log = AuditLog(self.database_path)

    def close(self) -> None:
        self.audit_log.close()
        self.connection.close()

    def _record_event(self, action: str, job: dict, actor: str = "system") -> None:
        self.audit_log.record(
            action=action,
            entity_type="processing_job",
            entity_id=job["job_id"],
            actor=actor,
            details={
                "job_type": job["job_type"],
                "status": job["status"],
                "attempts": job["attempts"],
                "progress": job["progress"],
                "error": job.get("error"),
            },
        )

    def enqueue(
        self,
        job_type: str,
        payload: dict,
        max_attempts: int = 3,
    ) -> dict:
        if not isinstance(job_type, str) or not job_type.strip():
            raise ValueError("Job type must be a non-empty string.")
        if not isinstance(payload, dict):
            raise TypeError("Job payload must be a dictionary.")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
            raise ValueError("Maximum attempts must be a positive integer.")

        try:
            serialized = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as error:
            raise ValueError("Job payload must be JSON serializable.") from error

        job_id = uuid.uuid4().hex
        now = _timestamp()
        self.connection.execute(
            """
            INSERT INTO processing_jobs (
                job_id, job_type, payload_json, status, progress,
                attempts, max_attempts, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', 0, 0, ?, ?, ?)
            """,
            (job_id, job_type.strip(), serialized, max_attempts, now, now),
        )
        job = self.get(job_id)
        self._record_event("job_enqueued", job)
        return job

    def get(self, job_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM processing_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return self._to_dict(row) if row else None

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        return item

    def list_jobs(self, statuses: list[str] | None = None, limit: int = 100) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Limit must be a positive integer.")
        if statuses is not None:
            if not isinstance(statuses, list) or any(
                status not in STATUSES for status in statuses
            ):
                raise ValueError("Unknown job status.")
            if not statuses:
                return []
            placeholders = ",".join("?" for _ in statuses)
            rows = self.connection.execute(
                f"""
                SELECT * FROM processing_jobs
                WHERE status IN ({placeholders})
                ORDER BY created_at DESC LIMIT ?
                """,
                (*statuses, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM processing_jobs
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._to_dict(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self.connection.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM processing_jobs
            GROUP BY status
            """
        ).fetchall()
        return {row["status"]: row["total"] for row in rows}

    def _recover_expired_jobs(self, cutoff: str) -> int:
        now = _timestamp()
        cursor = self.connection.execute(
            """
            UPDATE processing_jobs
            SET status = CASE
                    WHEN attempts >= max_attempts THEN 'failed'
                    ELSE 'queued'
                END,
                progress = CASE
                    WHEN attempts >= max_attempts THEN progress
                    ELSE 0
                END,
                locked_at = NULL,
                finished_at = CASE
                    WHEN attempts >= max_attempts THEN ?
                    ELSE NULL
                END,
                updated_at = ?,
                error = CASE
                    WHEN attempts >= max_attempts
                    THEN 'Worker lease expired; retry limit reached.'
                    ELSE 'Recovered after worker lease expired.'
                END
            WHERE status = 'running' AND locked_at < ?
            """,
            (now, now, cutoff),
        )
        return cursor.rowcount

    def recover_stale_jobs(self, lease_seconds: int = 900) -> int:
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or lease_seconds < 1
        ):
            raise ValueError("Lease duration must be a positive integer.")
        cutoff = _timestamp(_utc_now() - timedelta(seconds=lease_seconds))
        return self._recover_expired_jobs(cutoff)

    def recover_interrupted_jobs(self, lease_seconds: int = 900) -> int:
        """Recover expired jobs without stealing leases from active workers."""
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or lease_seconds < 1
        ):
            raise ValueError("Lease duration must be a positive integer.")
        cutoff = _timestamp(_utc_now() - timedelta(seconds=lease_seconds))
        return self._recover_expired_jobs(cutoff)

    def claim_next(self) -> dict | None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                """
                SELECT * FROM processing_jobs
                WHERE status = 'queued' AND attempts < max_attempts
                ORDER BY created_at, job_id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                self.connection.execute("COMMIT")
                return None

            now = _timestamp()
            cursor = self.connection.execute(
                """
                UPDATE processing_jobs
                SET status = 'running', attempts = attempts + 1,
                    started_at = COALESCE(started_at, ?),
                    locked_at = ?, updated_at = ?, error = NULL
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, now, now, row["job_id"]),
            )
            if cursor.rowcount != 1:
                self.connection.execute("ROLLBACK")
                return None
            claimed = self.get(row["job_id"])
            self.connection.execute("COMMIT")
            self._record_event("job_started", claimed)
            return claimed
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def update_progress(self, job_id: str, progress: float) -> dict:
        if (
            isinstance(progress, bool)
            or not isinstance(progress, (int, float))
            or not 0 <= progress <= 100
        ):
            raise ValueError("Progress must be between 0 and 100.")
        now = _timestamp()
        cursor = self.connection.execute(
            """
            UPDATE processing_jobs
            SET progress = ?, locked_at = ?, updated_at = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (float(progress), now, now, job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Only running jobs can update progress.")
        return self.get(job_id)

    def heartbeat(self, job_id: str) -> bool:
        now = _timestamp()
        cursor = self.connection.execute(
            """
            UPDATE processing_jobs
            SET locked_at = ?, updated_at = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (now, now, job_id),
        )
        return cursor.rowcount == 1

    def complete(self, job_id: str) -> dict:
        cursor = self.connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'completed', progress = 100,
                finished_at = ?, locked_at = NULL, updated_at = ?, error = NULL
            WHERE job_id = ? AND status = 'running'
            """,
            (_timestamp(), _timestamp(), job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Only running jobs can be completed.")
        job = self.get(job_id)
        self._record_event("job_completed", job)
        return job

    def fail(self, job_id: str, error: str, retry: bool = True) -> dict:
        if not isinstance(error, str) or not error.strip():
            raise ValueError("Failure details must be a non-empty string.")
        row = self.get(job_id)
        if row is None or row["status"] != "running":
            raise ValueError("Only running jobs can fail.")
        should_retry = retry and row["attempts"] < row["max_attempts"]
        status = "queued" if should_retry else "failed"
        now = _timestamp()
        self.connection.execute(
            """
            UPDATE processing_jobs
            SET status = ?, progress = CASE WHEN ? = 'queued' THEN 0 ELSE progress END,
                error = ?, locked_at = NULL,
                finished_at = ?, updated_at = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (
                status,
                status,
                error.strip()[:4000],
                None if should_retry else now,
                now,
                job_id,
            ),
        )
        job = self.get(job_id)
        self._record_event("job_failed" if status == "failed" else "job_retry_scheduled", job)
        return job

    def cancel(self, job_id: str) -> dict:
        """Cancel a queued job immediately or request cooperative cancellation."""
        now = _timestamp()
        cursor = self.connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'cancelled', locked_at = NULL,
                finished_at = ?, updated_at = ?
            WHERE job_id = ? AND status = 'queued'
            """,
            (now, now, job_id),
        )
        if cursor.rowcount == 1:
            job = self.get(job_id)
            self._record_event("job_cancelled", job)
            return job

        cursor = self.connection.execute(
            """
            UPDATE processing_jobs
            SET cancel_requested = 1, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND cancel_requested = 0
            """,
            (now, job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Only queued or running jobs can be cancelled.")
        job = self.get(job_id)
        self._record_event("job_cancellation_requested", job)
        return job

    def is_cancel_requested(self, job_id: str) -> bool:
        row = self.connection.execute(
            "SELECT cancel_requested FROM processing_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return bool(row["cancel_requested"]) if row else False

    def cancel_running(self, job_id: str) -> dict:
        cursor = self.connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'cancelled', locked_at = NULL,
                finished_at = ?, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND cancel_requested = 1
            """,
            (_timestamp(), _timestamp(), job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Only running jobs with a cancellation request can be cancelled.")
        job = self.get(job_id)
        self._record_event("job_cancelled", job)
        return job

    def retry(self, job_id: str) -> dict:
        cursor = self.connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'queued', attempts = 0, progress = 0,
                started_at = NULL, finished_at = NULL, locked_at = NULL,
                error = NULL, cancel_requested = 0, updated_at = ?
            WHERE job_id = ? AND status = 'failed'
            """,
            (_timestamp(), job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Only failed jobs can be retried manually.")
        job = self.get(job_id)
        self._record_event("job_manually_retried", job)
        return job
