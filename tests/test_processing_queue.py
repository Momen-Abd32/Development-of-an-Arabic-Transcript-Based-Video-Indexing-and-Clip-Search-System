import pytest

from src.media.processing_queue import ProcessingQueue


def test_enqueue_persists_job_and_payload_after_reopen(tmp_path):
    path = tmp_path / "queue.db"
    queue = ProcessingQueue(path)
    job = queue.enqueue("batch_import", {"input_directory": "/archive"}, 2)
    queue.close()

    reopened = ProcessingQueue(path)
    restored = reopened.get(job["job_id"])

    assert restored["status"] == "queued"
    assert restored["payload"] == {"input_directory": "/archive"}
    assert restored["attempts"] == 0
    assert restored["max_attempts"] == 2
    reopened.close()


def test_claim_progress_and_complete_lifecycle(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue("batch_import", {"input_directory": "archive"})
    claimed = queue.claim_next()

    assert claimed["job_id"] == job["job_id"]
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert queue.update_progress(job["job_id"], 42.5)["progress"] == 42.5

    completed = queue.complete(job["job_id"])
    assert completed["status"] == "completed"
    assert completed["progress"] == 100
    assert completed["finished_at"]
    assert queue.claim_next() is None
    queue.close()


def test_failed_job_retries_until_attempt_limit_then_can_be_manually_retried(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue("batch_import", {"input_directory": "archive"}, 2)

    first = queue.claim_next()
    queue.update_progress(job["job_id"], 60)
    failed_once = queue.fail(job["job_id"], "temporary error")
    assert failed_once["status"] == "queued"
    assert failed_once["attempts"] == 1
    assert failed_once["progress"] == 0

    second = queue.claim_next()
    assert second["attempts"] == 2
    failed_twice = queue.fail(job["job_id"], "permanent error")
    assert failed_twice["status"] == "failed"
    assert failed_twice["error"] == "permanent error"
    assert queue.claim_next() is None

    retried = queue.retry(job["job_id"])
    assert retried["status"] == "queued"
    assert retried["attempts"] == 0
    assert retried["progress"] == 0
    queue.close()


def test_queued_jobs_cancel_immediately_and_running_jobs_receive_request(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    queued = queue.enqueue("batch_import", {"input_directory": "archive"})
    assert queue.cancel(queued["job_id"])["status"] == "cancelled"

    running = queue.enqueue("batch_import", {"input_directory": "other"})
    queue.claim_next()
    requested = queue.cancel(running["job_id"])
    assert requested["status"] == "running"
    assert requested["cancel_requested"] == 1
    assert queue.is_cancel_requested(running["job_id"]) is True
    assert queue.cancel_running(running["job_id"])["status"] == "cancelled"
    assert queue.is_cancel_requested(running["job_id"]) is True
    queue.close()


def test_restart_recovery_requeues_interrupted_jobs(tmp_path):
    path = tmp_path / "queue.db"
    queue = ProcessingQueue(path)
    job = queue.enqueue("batch_import", {"input_directory": "archive"})
    queue.claim_next()
    queue.connection.execute(
        "UPDATE processing_jobs SET locked_at = '2000-01-01T00:00:00+00:00' WHERE job_id = ?",
        (job["job_id"],),
    )
    queue.close()

    restarted = ProcessingQueue(path)
    assert restarted.recover_interrupted_jobs(60) == 1
    recovered = restarted.get(job["job_id"])
    assert recovered["status"] == "queued"
    assert recovered["locked_at"] is None
    assert "worker lease expired" in recovered["error"]
    restarted.close()


def test_stale_lease_recovery_only_requeues_expired_running_jobs(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    stale = queue.enqueue("batch_import", {"input_directory": "stale"})
    fresh = queue.enqueue("batch_import", {"input_directory": "fresh"})
    queue.claim_next()
    queue.claim_next()

    queue.connection.execute(
        "UPDATE processing_jobs SET locked_at = '2000-01-01T00:00:00+00:00' WHERE job_id = ?",
        (stale["job_id"],),
    )

    assert queue.recover_stale_jobs(60) == 1
    assert queue.get(stale["job_id"])["status"] == "queued"
    assert queue.get(fresh["job_id"])["status"] == "running"
    queue.close()


@pytest.mark.parametrize("payload", [None, [], "text"])
def test_enqueue_rejects_non_dictionary_payload(tmp_path, payload):
    queue = ProcessingQueue(tmp_path / "queue.db")
    with pytest.raises(TypeError):
        queue.enqueue("batch_import", payload)
    queue.close()


def test_enqueue_rejects_non_json_payload_and_invalid_attempts(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    with pytest.raises(ValueError, match="JSON"):
        queue.enqueue("batch_import", {"path": object()})
    with pytest.raises(ValueError, match="Maximum attempts"):
        queue.enqueue("batch_import", {}, 0)
    queue.close()


@pytest.mark.parametrize("progress", [-1, 101, float("nan"), True])
def test_progress_rejects_invalid_values(tmp_path, progress):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue("batch_import", {})
    queue.claim_next()
    with pytest.raises(ValueError):
        queue.update_progress(job["job_id"], progress)
    queue.close()


def test_only_failed_jobs_can_be_manually_retried(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue("batch_import", {})
    with pytest.raises(ValueError, match="failed"):
        queue.retry(job["job_id"])
    queue.close()


def test_queue_lists_jobs_by_status(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    queued = queue.enqueue("batch_import", {"n": 1})
    cancelled = queue.enqueue("batch_import", {"n": 2})
    queue.cancel(cancelled["job_id"])

    results = queue.list_jobs(statuses=["queued"])
    assert [item["job_id"] for item in results] == [queued["job_id"]]
    assert queue.list_jobs(statuses=[]) == []
    queue.close()

def test_two_queue_workers_cannot_claim_the_same_job(tmp_path):
    path = tmp_path / "queue.db"
    first_worker = ProcessingQueue(path)
    second_worker = ProcessingQueue(path)
    job = first_worker.enqueue("batch_import", {"input_directory": "archive"})

    claimed = first_worker.claim_next()
    competing_claim = second_worker.claim_next()

    assert claimed["job_id"] == job["job_id"]
    assert competing_claim is None
    first_worker.close()
    second_worker.close()

def test_queue_counts_all_jobs_by_status(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    queue.enqueue("batch_import", {"n": 1})
    cancelled = queue.enqueue("batch_import", {"n": 2})
    queue.cancel(cancelled["job_id"])

    assert queue.count_by_status() == {"cancelled": 1, "queued": 1}
    queue.close()

def test_worker_heartbeat_only_renews_running_jobs(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue("batch_import", {})
    queue.claim_next()

    assert queue.heartbeat(job["job_id"]) is True
    queue.complete(job["job_id"])
    assert queue.heartbeat(job["job_id"]) is False
    queue.close()

def test_expired_job_at_attempt_limit_becomes_failed_not_stuck_queued(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue("batch_import", {}, max_attempts=1)
    queue.claim_next()
    queue.connection.execute(
        "UPDATE processing_jobs SET locked_at = '2000-01-01T00:00:00+00:00' WHERE job_id = ?",
        (job["job_id"],),
    )

    assert queue.recover_stale_jobs(60) == 1
    recovered = queue.get(job["job_id"])
    assert recovered["status"] == "failed"
    assert recovered["finished_at"] is not None
    assert "retry limit reached" in recovered["error"]
    assert queue.claim_next() is None
    queue.close()

def test_queue_lifecycle_is_written_to_audit_log(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue("batch_import", {"input_directory": "archive"})
    queue.claim_next()
    queue.update_progress(job["job_id"], 25)
    queue.complete(job["job_id"])

    events = queue.audit_log.list_events(
        entity_type="processing_job", entity_id=job["job_id"]
    )
    assert {event["action"] for event in events} == {
        "job_enqueued", "job_started", "job_completed"
    }
    assert all(event["actor"] == "system" for event in events)
    queue.close()

def test_cancel_request_is_persisted_after_reopening_queue(tmp_path):
    path = tmp_path / "queue.db"
    queue = ProcessingQueue(path)
    job = queue.enqueue("batch_import", {})
    queue.claim_next()
    queue.cancel(job["job_id"])
    queue.close()

    reopened = ProcessingQueue(path)
    assert reopened.is_cancel_requested(job["job_id"]) is True
    reopened.close()

def test_expired_worker_finishes_pending_cancellation_instead_of_requeueing(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue("batch_import", {}, max_attempts=3)
    queue.claim_next()
    queue.cancel(job["job_id"])
    queue.connection.execute(
        "UPDATE processing_jobs SET locked_at = '2000-01-01T00:00:00+00:00' WHERE job_id = ?",
        (job["job_id"],),
    )

    assert queue.recover_stale_jobs(60) == 1
    recovered = queue.get(job["job_id"])
    assert recovered["status"] == "cancelled"
    assert recovered["finished_at"] is not None
    assert "cancellation completed" in recovered["error"].lower()
    assert queue.claim_next() is None
    events = queue.audit_log.list_events(
        entity_type="processing_job", entity_id=job["job_id"]
    )
    assert "job_cancelled" in {event["action"] for event in events}
    queue.close()

def test_existing_queue_database_is_migrated_for_cancel_requests(tmp_path):
    import sqlite3

    path = tmp_path / "legacy_queue.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE processing_jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                locked_at TEXT,
                error TEXT
            )
        """)

    queue = ProcessingQueue(path)
    columns = {
        row["name"]
        for row in queue.connection.execute("PRAGMA table_info(processing_jobs)")
    }
    assert "cancel_requested" in columns
    assert {"stage", "current_file", "stage_progress"}.issubset(columns)
    queued = queue.enqueue("batch_import", {})
    assert queued["cancel_requested"] == 0
    assert queued["stage"] == "queued"
    assert queued["current_file"] is None
    assert queued["stage_progress"] == 0
    queue.close()



def test_processing_stage_updates_are_persisted_and_validated(tmp_path):
    queue = ProcessingQueue(tmp_path / "queue.db")
    job = queue.enqueue("batch_import", {})
    with pytest.raises(ValueError, match="running jobs"):
        queue.update_stage(job["job_id"], "transcribing")

    queue.claim_next()
    updated = queue.update_stage(
        job["job_id"],
        "transcribing",
        current_file="/archive/interview.mp4",
        stage_progress=62.5,
    )
    assert updated["stage"] == "transcribing"
    assert updated["current_file"] == "/archive/interview.mp4"
    assert updated["stage_progress"] == 62.5

    with pytest.raises(ValueError, match="non-empty"):
        queue.update_stage(job["job_id"], " ")
    with pytest.raises(ValueError, match="non-empty string or None"):
        queue.update_stage(job["job_id"], "transcribing", current_file=" ")
    for invalid in (-1, 101, float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="Stage progress"):
            queue.update_stage(job["job_id"], "transcribing", stage_progress=invalid)

    queue.complete(job["job_id"])
    completed = queue.get(job["job_id"])
    assert completed["stage"] == "completed"
    assert completed["stage_progress"] == 100
    assert completed["current_file"] is None
    queue.close()


def test_retry_and_recovery_reset_stage_state(tmp_path):
    path = tmp_path / "queue.db"
    queue = ProcessingQueue(path)
    job = queue.enqueue("batch_import", {})
    queue.claim_next()
    queue.update_stage(job["job_id"], "transcribing", "/archive/a.mp4", 55)
    failed = queue.fail(job["job_id"], "temporary error")
    assert failed["status"] == "queued"
    assert failed["stage"] == "retry_wait"
    assert failed["stage_progress"] == 0

    queue.claim_next()
    queue.update_stage(job["job_id"], "indexing_transcript", "/archive/a.mp4", 90)
    queue.connection.execute(
        "UPDATE processing_jobs SET locked_at = '2000-01-01T00:00:00+00:00' WHERE job_id = ?",
        (job["job_id"],),
    )
    assert queue.recover_stale_jobs(60) == 1
    recovered = queue.get(job["job_id"])
    assert recovered["stage"] == "queued"
    assert recovered["current_file"] is None
    assert recovered["stage_progress"] == 0
    queue.close()
