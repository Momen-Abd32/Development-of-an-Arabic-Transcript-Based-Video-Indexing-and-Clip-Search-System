"""Read-only archive and runtime health metrics for the dashboard."""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

from src.media.media_catalog import MediaCatalog
from src.media.processing_queue import ProcessingQueue


class ArchiveMetrics:
    def __init__(
        self,
        catalog_path: str | Path = "data/database/media_catalog.json",
        queue_path: str | Path = "data/database/processing_queue.db",
        database_path: str | Path = "data/database/videos.db",
        transcript_dir: str | Path = "data/transcripts",
    ):
        self.catalog = MediaCatalog(str(catalog_path))
        self.queue = ProcessingQueue(queue_path)
        self.database_path = Path(database_path)
        self.transcript_dir = Path(transcript_dir)

    def close(self) -> None:
        self.queue.close()

    def collect(self) -> dict:
        records = self.catalog.get_all()
        status_counts = Counter(item["status"] for item in records)
        media_type_counts = Counter(item["media_type"] for item in records)

        storage_bytes = 0
        missing_files = 0
        for item in records:
            media_path = Path(item["stored_path"])
            if media_path.is_file():
                storage_bytes += media_path.stat().st_size
            else:
                missing_files += 1

        jobs = self.queue.list_jobs(limit=100000)
        job_counts = Counter(item["status"] for item in jobs)
        transcript_count = (
            len(list(self.transcript_dir.glob("*.json")))
            if self.transcript_dir.exists()
            else 0
        )

        if self.database_path.is_file():
            try:
                with sqlite3.connect(self.database_path, timeout=5) as connection:
                    row = connection.execute("PRAGMA quick_check").fetchone()
                    database_health = row[0] if row else "unknown"
            except sqlite3.Error as error:
                database_health = f"error: {error}"
        else:
            database_health = "not_initialized"

        return {
            "media_total": len(records),
            "video_total": media_type_counts.get("video", 0),
            "audio_total": media_type_counts.get("audio", 0),
            "status_counts": dict(status_counts),
            "storage_bytes": storage_bytes,
            "missing_files": missing_files,
            "transcript_total": transcript_count,
            "queue_counts": dict(job_counts),
            "database_health": database_health,
            "ffmpeg_available": shutil.which("ffmpeg") is not None,
            "faster_whisper_available": importlib.util.find_spec("faster_whisper") is not None,
            "semantic_search_available": importlib.util.find_spec("sentence_transformers") is not None,
            "diarization_available": importlib.util.find_spec("pyannote") is not None,
        }
