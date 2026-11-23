"""Polling-based watched-folder ingestion that queues only stable new files."""
from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from pathlib import Path

from src.media.batch_processor import SUPPORTED_EXTENSIONS
from src.media.processing_queue import ProcessingQueue


class FolderWatcher:
    """Detect stable media files and enqueue explicit file-import jobs.

    A file must retain the same size and modification timestamp for the
    configured number of consecutive scans before it is queued. This avoids
    importing files while another process is still copying them.
    """

    def __init__(
        self,
        folders: list[str | Path],
        *,
        database_path: str | Path = "data/database/processing_queue.db",
        recursive: bool = True,
        stable_scans: int = 2,
        queue: ProcessingQueue | None = None,
    ):
        if not isinstance(folders, (list, tuple)) or not folders:
            raise ValueError("At least one watched folder is required.")
        if isinstance(stable_scans, bool) or not isinstance(stable_scans, int) or stable_scans < 2:
            raise ValueError("Stable scans must be an integer of at least two.")
        if not isinstance(recursive, bool):
            raise TypeError("Recursive must be a boolean.")

        resolved_folders = []
        for folder in folders:
            if not isinstance(folder, (str, Path)):
                raise TypeError("Watched folder paths must be strings or Path objects.")
            path = Path(folder).expanduser().resolve()
            if not path.exists() or not path.is_dir():
                raise ValueError(f"Watched folder is not an existing directory: {path}")
            if path not in resolved_folders:
                resolved_folders.append(path)

        self.folders = resolved_folders
        self.recursive = recursive
        self.stable_scans = stable_scans
        self.queue = queue or ProcessingQueue(database_path)
        self._owns_queue = queue is None
        self._stop_event = threading.Event()
        self.queue.connection.execute("""
            CREATE TABLE IF NOT EXISTS watched_media_files (
                file_path TEXT PRIMARY KEY,
                folder_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                stable_scans INTEGER NOT NULL DEFAULT 1,
                queued_signature TEXT,
                last_seen_at TEXT NOT NULL
            )
        """)
        self.queue.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_watched_media_folder
            ON watched_media_files(folder_path, last_seen_at)
        """)

    def close(self) -> None:
        if self._owns_queue:
            self.queue.close()

    @staticmethod
    def _signature(size_bytes: int, mtime_ns: int) -> str:
        return f"{size_bytes}:{mtime_ns}"

    def _iter_files(self, folder: Path):
        candidates = folder.rglob("*") if self.recursive else folder.iterdir()
        for path in sorted(candidates, key=lambda item: str(item).lower()):
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(folder)
                if resolved.is_file():
                    yield resolved
            except (OSError, ValueError):
                continue

    def scan_once(self) -> dict | None:
        """Scan all configured folders once and queue stable, changed files."""
        ready: dict[str, tuple[str, str]] = {}
        now = datetime.now(timezone.utc).isoformat()

        for folder in self.folders:
            for path in self._iter_files(folder):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size <= 0:
                    continue
                file_path = str(path)
                signature = self._signature(stat.st_size, stat.st_mtime_ns)
                row = self.queue.connection.execute(
                    """
                    SELECT size_bytes, mtime_ns, stable_scans, queued_signature
                    FROM watched_media_files
                    WHERE file_path = ?
                    """,
                    (file_path,),
                ).fetchone()

                if row is None:
                    self.queue.connection.execute(
                        """
                        INSERT INTO watched_media_files (
                            file_path, folder_path, size_bytes, mtime_ns,
                            stable_scans, queued_signature, last_seen_at
                        ) VALUES (?, ?, ?, ?, 1, NULL, ?)
                        """,
                        (file_path, str(folder), stat.st_size, stat.st_mtime_ns, now),
                    )
                    continue

                same_signature = (
                    row["size_bytes"] == stat.st_size
                    and row["mtime_ns"] == stat.st_mtime_ns
                )
                stable_count = row["stable_scans"] + 1 if same_signature else 1
                queued_signature = (
                    row["queued_signature"] if same_signature else None
                )
                self.queue.connection.execute(
                    """
                    UPDATE watched_media_files
                    SET folder_path = ?, size_bytes = ?, mtime_ns = ?,
                        stable_scans = ?, queued_signature = ?, last_seen_at = ?
                    WHERE file_path = ?
                    """,
                    (
                        str(folder), stat.st_size, stat.st_mtime_ns,
                        stable_count, queued_signature, now, file_path,
                    ),
                )
                if (
                    stable_count >= self.stable_scans
                    and queued_signature != signature
                ):
                    ready[file_path] = (signature, str(folder))

        if not ready:
            return None

        files = sorted(ready)
        job = self.queue.enqueue(
            "file_import",
            {"files": files, "source": "watched_folder"},
            max_attempts=3,
        )
        for file_path, (signature, _folder) in ready.items():
            self.queue.connection.execute(
                """
                UPDATE watched_media_files
                SET queued_signature = ?, last_seen_at = ?
                WHERE file_path = ?
                """,
                (signature, now, file_path),
            )
        return job

    def run_forever(self, poll_seconds: float = 5) -> None:
        if isinstance(poll_seconds, bool) or not isinstance(
            poll_seconds, (int, float)
        ):
            raise ValueError("Polling interval must be a finite positive number.")
        try:
            interval = float(poll_seconds)
        except (OverflowError, ValueError) as error:
            raise ValueError(
                "Polling interval must be a finite positive number."
            ) from error
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Polling interval must be a finite positive number.")
        self._stop_event.clear()
        while not self._stop_event.is_set():
            self.scan_once()
            self._stop_event.wait(interval)

    def stop(self) -> None:
        self._stop_event.set()
