from scripts import import_media_url


def test_remote_url_cli_downloads_and_enqueues_file_import(monkeypatch, capsys):
    calls = {}

    class FakeAdapter:
        def __init__(self, allowed_hosts, download_directory, **kwargs):
            calls["allowed_hosts"] = allowed_hosts
            calls["download_directory"] = download_directory
            calls["adapter_kwargs"] = kwargs

        def download(self, url):
            calls.setdefault("urls", []).append(url)
            return {
                "path": "data/incoming/remote/file.mp4",
                "source_host": "media.example.com",
                "size_bytes": 12,
                "sha256": "a" * 64,
            }

    class FakeQueue:
        def __init__(self, database):
            calls["database"] = database

        def enqueue(self, job_type, payload, max_attempts):
            calls["job"] = (job_type, payload, max_attempts)
            return {"job_id": "job-123"}

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(import_media_url, "RemoteURLAdapter", FakeAdapter)
    monkeypatch.setattr(import_media_url, "ProcessingQueue", FakeQueue)
    monkeypatch.setattr(
        "sys.argv",
        [
            "import_media_url.py",
            "--url", "https://media.example.com/file.mp4",
            "--allowed-host", "media.example.com",
            "--download-directory", "incoming",
            "--database", "queue.db",
        ],
    )

    assert import_media_url.main() == 0
    assert calls["allowed_hosts"] == ["media.example.com"]
    assert calls["download_directory"] == "incoming"
    assert calls["database"] == "queue.db"
    assert calls["job"] == (
        "file_import",
        {
            "files": ["data/incoming/remote/file.mp4"],
            "source": "remote_url",
            "source_host": "media.example.com",
        },
        3,
    )
    assert calls["closed"] is True
    assert '"job_id": "job-123"' in capsys.readouterr().out


def test_remote_url_cli_reports_download_failure(monkeypatch, capsys):
    class FailingAdapter:
        def __init__(self, allowed_hosts, download_directory, **kwargs):
            pass

        def download(self, url):
            raise ValueError("host is not allowlisted")

    class FakeQueue:
        def __init__(self, database):
            pass

        def close(self):
            pass

    monkeypatch.setattr(import_media_url, "RemoteURLAdapter", FailingAdapter)
    monkeypatch.setattr(import_media_url, "ProcessingQueue", FakeQueue)
    monkeypatch.setattr(
        "sys.argv",
        [
            "import_media_url.py",
            "--url", "https://media.example.com/file.mp4",
            "--allowed-host", "media.example.com",
        ],
    )

    assert import_media_url.main() == 1
    assert "host is not allowlisted" in capsys.readouterr().out
