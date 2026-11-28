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


class CancellingProcessor:
    def __init__(self, queue, job_id):
        self.queue = queue
        self.job_id = job_id

    def process_directory(self, input_directory, recursive=True, progress_callback=None):
        self.queue.cancel(self.job_id)
        if progress_callback:
            progress_callback(1, 2)
        raise AssertionError("The worker should stop after the cancellation callback.")


def test_worker_stops_between_files_when_active_job_is_cancelled(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue(
        "batch_import",
        {"input_directory": "archive"},
    )
    worker = ProcessingWorker(
        queue=queue,
        processor_factory=lambda: CancellingProcessor(queue, job["job_id"]),
        lease_seconds=3,
        heartbeat_interval=1,
    )

    result = worker.run_once()

    assert result["job"]["status"] == "cancelled"
    assert result["job"]["progress"] == 50
    assert result["job"]["cancel_requested"] == 1
    events = queue.audit_log.list_events(
        entity_type="processing_job", entity_id=job["job_id"]
    )
    assert "job_cancellation_requested" in {event["action"] for event in events}
    assert "job_cancelled" in {event["action"] for event in events}
    queue.close()



class StageAwareProcessor:
    def process_directory(
        self,
        input_directory,
        recursive=True,
        progress_callback=None,
        stage_callback=None,
    ):
        if stage_callback:
            stage_callback("extracting_audio", "archive/interview.mp4", 35)
            stage_callback("transcribing", "archive/interview.mp4", 60)
            stage_callback("indexing_transcript", "archive/interview.mp4", 90)
        if progress_callback:
            progress_callback(1, 1)
        return [{"source": "interview.mp4", "status": "processed", "segments": 4}]


def test_worker_persists_stage_callback_updates_without_breaking_old_processors(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue(
        "batch_import",
        {"input_directory": "archive"},
    )
    updates = []
    original_update_stage = queue.update_stage

    def track_stage(job_id, stage, current_file=None, stage_progress=0):
        updates.append((stage, current_file, stage_progress))
        return original_update_stage(
            job_id,
            stage,
            current_file=current_file,
            stage_progress=stage_progress,
        )

    queue.update_stage = track_stage
    worker = ProcessingWorker(
        queue=queue,
        processor_factory=StageAwareProcessor,
        lease_seconds=3,
        heartbeat_interval=1,
    )

    result = worker.run_once()

    assert result["job"]["status"] == "completed"
    assert updates == [
        ("extracting_audio", "archive/interview.mp4", 35),
        ("transcribing", "archive/interview.mp4", 60),
        ("indexing_transcript", "archive/interview.mp4", 90),
    ]
    assert result["job"]["stage"] == "completed"
    queue.close()



class ExplicitFileProcessor:
    def process_files(
        self,
        files,
        progress_callback=None,
        stage_callback=None,
        recursive=True,
    ):
        if stage_callback:
            stage_callback("verifying_source", files[0], 0)
            stage_callback("verifying_source", files[0], 100)
        if progress_callback:
            progress_callback(1, len(files))
        return [
            {"source": path, "status": "processed", "segments": 2}
            for path in files
        ]


def test_worker_dispatches_explicit_file_import_jobs(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue(
        "file_import",
        {"files": ["archive/one.mp4", "archive/two.mp3"]},
    )
    worker = ProcessingWorker(
        queue=queue,
        processor_factory=ExplicitFileProcessor,
        lease_seconds=3,
        heartbeat_interval=1,
    )

    result = worker.run_once()

    assert "error" not in result, result.get("error")
    assert result["job"]["job_id"] == job["job_id"]
    assert result["job"]["status"] == "completed"
    assert len(result["results"]) == 2
    assert result["job"]["stage"] == "completed"
    queue.close()
