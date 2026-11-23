from src.media.processing_queue import ProcessingQueue
from src.media.processing_worker import ProcessingWorker


class SuccessfulProcessor:
    def process_directory(self, input_directory, recursive=True, progress_callback=None):
        if progress_callback:
            progress_callback(1, 2)
            progress_callback(2, 2)
        return [
            {"source": "one.mp4", "status": "processed", "segments": 2},
            {"source": "two.mp3", "status": "already_transcribed", "segments": 1},
        ]


class FailedProcessor:
    def process_directory(self, input_directory, recursive=True, progress_callback=None):
        if progress_callback:
            progress_callback(1, 1)
        return [
            {
                "source": "bad.mp4",
                "status": "failed",
                "segments": 0,
                "error": "invalid media",
            }
        ]


def test_worker_processes_job_and_persists_completion(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue(
        "batch_import",
        {"input_directory": "archive", "recursive": True},
    )
    worker = ProcessingWorker(
        queue=queue,
        processor_factory=SuccessfulProcessor,
        lease_seconds=3,
        heartbeat_interval=1,
    )

    result = worker.run_once()

    assert result["job"]["job_id"] == job["job_id"]
    assert result["job"]["status"] == "completed"
    assert result["job"]["progress"] == 100
    assert [item["status"] for item in result["results"]] == [
        "processed",
        "already_transcribed",
    ]
    assert worker.run_once() is None
    queue.close()


def test_worker_requeues_failed_batch_for_retry(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue(
        "batch_import",
        {"input_directory": "archive"},
        max_attempts=2,
    )
    worker = ProcessingWorker(
        queue=queue,
        processor_factory=FailedProcessor,
        lease_seconds=3,
        heartbeat_interval=1,
    )

    result = worker.run_once()

    assert result["job"]["job_id"] == job["job_id"]
    assert result["job"]["status"] == "queued"
    assert result["job"]["attempts"] == 1
    assert result["job"]["progress"] == 0
    assert "invalid media" in result["job"]["error"]
    queue.close()


def test_worker_handles_empty_queue_without_processing(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    worker = ProcessingWorker(
        queue=queue,
        processor_factory=SuccessfulProcessor,
        lease_seconds=3,
        heartbeat_interval=1,
    )

    assert worker.run_once() is None
    queue.close()


def test_worker_rejects_invalid_lease_or_poll_interval(tmp_path):
    import pytest

    queue = ProcessingQueue(tmp_path / "queue.db")
    with pytest.raises(ValueError):
        ProcessingWorker(queue=queue, lease_seconds=2)
    worker = ProcessingWorker(queue=queue, lease_seconds=3)
    with pytest.raises(ValueError):
        worker.run_forever(poll_seconds=0)
    queue.close()
