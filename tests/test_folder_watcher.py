import pytest

from src.media.folder_watcher import FolderWatcher
from src.media.processing_queue import ProcessingQueue


def test_watcher_waits_for_stable_file_and_enqueues_once(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    media = folder / "interview.mp4"
    media.write_bytes(b"first complete media")

    watcher = FolderWatcher(
        [folder],
        database_path=tmp_path / "queue.db",
        stable_scans=2,
    )
    try:
        assert watcher.scan_once() is None
        job = watcher.scan_once()

        assert job["job_type"] == "file_import"
        assert job["payload"]["files"] == [str(media.resolve())]
        assert job["payload"]["source"] == "watched_folder"
        assert watcher.scan_once() is None
        assert len(watcher.queue.list_jobs()) == 1
    finally:
        watcher.close()


def test_watcher_detects_a_changed_file_after_it_becomes_stable(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    media = folder / "recording.wav"
    media.write_bytes(b"initial bytes")

    watcher = FolderWatcher([folder], database_path=tmp_path / "queue.db")
    try:
        assert watcher.scan_once() is None
        first_job = watcher.scan_once()
        assert first_job is not None

        media.write_bytes(b"changed media bytes with a new size")
        assert watcher.scan_once() is None
        second_job = watcher.scan_once()

        assert second_job is not None
        assert second_job["job_id"] != first_job["job_id"]
        assert len(watcher.queue.list_jobs()) == 2
    finally:
        watcher.close()


def test_watcher_ignores_unsupported_files_and_honors_non_recursive_mode(tmp_path):
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "notes.txt").write_text("ignore", encoding="utf-8")
    (nested / "nested.mp3").write_bytes(b"nested audio")

    watcher = FolderWatcher(
        [root],
        database_path=tmp_path / "queue.db",
        recursive=False,
    )
    try:
        assert watcher.scan_once() is None
        assert watcher.scan_once() is None
        assert watcher.queue.list_jobs() == []
    finally:
        watcher.close()


def test_watcher_scans_nested_media_when_recursive(tmp_path):
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    media = nested / "nested.mp3"
    media.write_bytes(b"nested audio")

    watcher = FolderWatcher(
        [root],
        database_path=tmp_path / "queue.db",
        recursive=True,
    )
    try:
        assert watcher.scan_once() is None
        job = watcher.scan_once()
        assert job["payload"]["files"] == [str(media.resolve())]
    finally:
        watcher.close()


def test_watcher_state_survives_restart(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    media = root / "video.mkv"
    media.write_bytes(b"media")

    first = FolderWatcher([root], database_path=tmp_path / "queue.db")
    assert first.scan_once() is None
    first.close()

    second = FolderWatcher([root], database_path=tmp_path / "queue.db")
    try:
        job = second.scan_once()
        assert job is not None
        assert job["payload"]["files"] == [str(media.resolve())]
    finally:
        second.close()


def test_watcher_can_use_an_injected_queue_without_closing_it(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    queue = ProcessingQueue(tmp_path / "queue.db")
    watcher = FolderWatcher([root], queue=queue)
    watcher.close()

    queued = queue.enqueue("batch_import", {})
    assert queue.get(queued["job_id"]) is not None
    queue.close()


@pytest.mark.parametrize("stable_scans", [0, 1, True, 1.5])
def test_watcher_rejects_invalid_stability_threshold(tmp_path, stable_scans):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        FolderWatcher(
            [root],
            database_path=tmp_path / "queue.db",
            stable_scans=stable_scans,
        )


@pytest.mark.parametrize("folders", [[], None, "not-a-list"])
def test_watcher_requires_a_folder_list(tmp_path, folders):
    with pytest.raises(ValueError):
        FolderWatcher(folders, database_path=tmp_path / "queue.db")


def test_watcher_rejects_missing_folder(tmp_path):
    with pytest.raises(ValueError, match="existing directory"):
        FolderWatcher([tmp_path / "missing"], database_path=tmp_path / "queue.db")


def test_watcher_rejects_invalid_poll_interval(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    watcher = FolderWatcher([root], database_path=tmp_path / "queue.db")
    try:
        with pytest.raises(ValueError):
            watcher.run_forever(0)
    finally:
        watcher.close()
