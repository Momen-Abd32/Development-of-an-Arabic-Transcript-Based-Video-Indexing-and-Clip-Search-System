from scripts import watch_media_folders


def test_watcher_cli_passes_folder_and_polling_options(monkeypatch):
    calls = {}

    class FakeWatcher:
        def __init__(self, folders, **kwargs):
            calls["folders"] = folders
            calls["kwargs"] = kwargs

        def run_forever(self, poll_seconds):
            calls["poll_seconds"] = poll_seconds

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(watch_media_folders, "FolderWatcher", FakeWatcher)
    monkeypatch.setattr(
        "sys.argv",
        [
            "watch_media_folders.py",
            "--folder", "/archive/a",
            "--folder", "/archive/b",
            "--poll-seconds", "2.5",
            "--stable-scans", "3",
            "--non-recursive",
            "--database", "/tmp/watcher.db",
        ],
    )

    assert watch_media_folders.main() == 0
    assert calls["folders"] == ["/archive/a", "/archive/b"]
    assert calls["kwargs"] == {
        "database_path": "/tmp/watcher.db",
        "recursive": False,
        "stable_scans": 3,
    }
    assert calls["poll_seconds"] == 2.5
    assert calls["closed"] is True
