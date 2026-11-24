from scripts import import_s3_media


def test_s3_cli_downloads_and_enqueues_shared_file_import(monkeypatch, capsys):
    calls = {}

    class FakeAdapter:
        @classmethod
        def from_boto3(cls, allowed_buckets, download_directory, **kwargs):
            calls["allowed_buckets"] = allowed_buckets
            calls["download_directory"] = download_directory
            calls["adapter_kwargs"] = kwargs
            return cls()

        def download(self, bucket, key):
            calls.setdefault("objects", []).append((bucket, key))
            return {
                "path": "data/incoming/cloud/file.mp4",
                "bucket": bucket,
                "key": key,
                "size_bytes": 10,
                "sha256": "a" * 64,
            }

    class FakeQueue:
        def __init__(self, database):
            calls["database"] = database

        def enqueue(self, job_type, payload, max_attempts):
            calls["job"] = (job_type, payload, max_attempts)
            return {"job_id": "cloud-job"}

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(import_s3_media, "S3ObjectAdapter", FakeAdapter)
    monkeypatch.setattr(import_s3_media, "ProcessingQueue", FakeQueue)
    monkeypatch.setattr("sys.argv", [
        "import_s3_media.py",
        "--bucket", "archive-bucket",
        "--key", "media/interview.mp4",
        "--allowed-bucket", "archive-bucket",
        "--profile", "archive-profile",
        "--download-directory", "incoming",
        "--database", "queue.db",
    ])

    assert import_s3_media.main() == 0
    assert calls["allowed_buckets"] == ["archive-bucket"]
    assert calls["objects"] == [("archive-bucket", "media/interview.mp4")]
    assert calls["adapter_kwargs"]["profile_name"] == "archive-profile"
    assert calls["database"] == "queue.db"
    assert calls["job"] == (
        "file_import",
        {
            "files": ["data/incoming/cloud/file.mp4"],
            "source": "s3_object",
            "bucket": "archive-bucket",
            "object_key": "media/interview.mp4",
        },
        3,
    )
    assert calls["closed"] is True
    assert '"job_id": "cloud-job"' in capsys.readouterr().out


def test_s3_cli_rejects_mismatched_bucket_and_key_counts(monkeypatch):
    monkeypatch.setattr("sys.argv", [
        "import_s3_media.py",
        "--bucket", "archive-bucket",
        "--key", "one.mp4",
        "--key", "two.mp4",
        "--allowed-bucket", "archive-bucket",
    ])

    import pytest
    with pytest.raises(SystemExit) as error:
        import_s3_media.main()
    assert error.value.code == 2
