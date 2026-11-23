"""Background worker for durable media-processing jobs."""
from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path
from typing import Callable

from src.media.batch_processor import MediaBatchProcessor
from src.media.processing_queue import ProcessingQueue


class ProcessingCancelled(Exception):
    """Raised between media files when a running job is cancelled."""


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
            def report_progress(completed: int, total: int) -> None:
                self.queue.update_progress(
                    job["job_id"],
                    100 * completed / max(total, 1),
                )
                if self.queue.is_cancel_requested(job["job_id"]):
                    raise ProcessingCancelled("Cancellation requested by user.")

            def report_stage(
                stage: str,
                current_file: str | None,
                stage_progress: float,
            ) -> None:
                self.queue.update_stage(
                    job["job_id"],
                    stage,
                    current_file=current_file,
                    stage_progress=stage_progress,
                )

            if job["job_type"] == "batch_import":
                process_method = processor.process_directory
                process_args = (payload["input_directory"],)
                process_kwargs = {
                    "recursive": payload.get("recursive", True),
                    "progress_callback": report_progress,
                }
            elif job["job_type"] == "file_import":
                process_method = getattr(processor, "process_files", None)
                if not callable(process_method):
                    raise TypeError(
                        "The configured processor does not support file imports."
                    )
                process_args = (payload["files"],)
                process_kwargs = {
                    "progress_callback": report_progress,
                }
            else:
                raise ValueError(
                    f'Unsupported processing job type: {job["job_type"]}'
                )

            try:
                parameters = inspect.signature(process_method).parameters.values()
                supports_stage_callback = any(
                    parameter.name == "stage_callback"
                    or parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                )
            except (TypeError, ValueError):
                supports_stage_callback = False
            if supports_stage_callback:
                process_kwargs["stage_callback"] = report_stage

            results = process_method(*process_args, **process_kwargs)
            if self.queue.is_cancel_requested(job["job_id"]):
                final_job = self.queue.cancel_running(job["job_id"])
                return {"job": final_job, "results": results}
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
        except ProcessingCancelled:
            final_job = self.queue.cancel_running(job["job_id"])
            return {"job": final_job, "results": []}
        except Exception as error:
            if self.queue.is_cancel_requested(job["job_id"]):
                final_job = self.queue.cancel_running(job["job_id"])
                return {"job": final_job, "results": [], "error": str(error)}
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
