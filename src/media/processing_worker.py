"""Background worker for durable media-processing jobs."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from src.media.batch_processor import MediaBatchProcessor
from src.media.processing_queue import ProcessingQueue


class ProcessingWorker:
    def __init__(
        self,
        queue: ProcessingQueue | None = None,
        processor_factory: Callable[[], MediaBatchProcessor] = MediaBatchProcessor,
        lease_seconds: int = 900,
        heartbeat_interval: int | None = None,
    ):
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds < 3:
            raise ValueError("Worker lease must be at least three seconds.")
        interval = heartbeat_interval or max(1, lease_seconds // 3)
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
            raise ValueError("Heartbeat interval must be a positive integer.")

        self.queue = queue or ProcessingQueue()
        self._owns_queue = queue is None
        self.processor_factory = processor_factory
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = interval
        self._shutdown_event = threading.Event()

    def close(self) -> None:
        if self._owns_queue:
            self.queue.close()

    def stop(self) -> None:
        self._shutdown_event.set()

    def _heartbeat_loop(self, job_id: str, stop_event: threading.Event) -> None:
        heartbeat_queue = ProcessingQueue(self.queue.database_path)
        try:
            while not stop_event.wait(self.heartbeat_interval):
                if not heartbeat_queue.heartbeat(job_id):
                    return
        finally:
            heartbeat_queue.close()

    def run_once(self) -> dict | None:
        self.queue.recover_stale_jobs(self.lease_seconds)
        job = self.queue.claim_next()
        if job is None:
            return None

        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job["job_id"], heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()

        try:
            payload = job["payload"]
            processor = self.processor_factory()
            results = processor.process_directory(
                payload["input_directory"],
                recursive=payload.get("recursive", True),
                progress_callback=lambda completed, total: self.queue.update_progress(
                    job["job_id"],
                    100 * completed / max(total, 1),
                ),
            )
            failures = [item for item in results if item.get("status") == "failed"]
            if failures:
                detail = "; ".join(
                    f'{item.get("source", "unknown source")}: '
                    f'{item.get("error", "unknown processing error")}'
                    for item in failures
                )
                final_job = self.queue.fail(job["job_id"], detail)
            else:
                final_job = self.queue.complete(job["job_id"])
            return {"job": final_job, "results": results}
        except Exception as error:
            final_job = self.queue.fail(job["job_id"], str(error))
            return {"job": final_job, "results": [], "error": str(error)}
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=self.heartbeat_interval + 1)

    def run_forever(self, poll_seconds: float = 5) -> None:
        if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, (int, float)) or poll_seconds <= 0:
            raise ValueError("Polling interval must be a positive number.")
        self._shutdown_event.clear()
        while not self._shutdown_event.is_set():
            result = self.run_once()
            if result is None:
                self._shutdown_event.wait(poll_seconds)
