import hashlib
import io

import pytest

from src.media.cloud_ingestion import CloudIngestionError, S3ObjectAdapter


class FakeS3:
    def __init__(self, data=b"sample media", content_type="video/mp4"):
        self.data = data
        self.content_type = content_type
        self.calls = []

    def head_object(self, *, Bucket, Key):
        self.calls.append(("head", Bucket, Key))
        return {
            "ContentLength": len(self.data),
            "ContentType": self.content_type,
        }

    def get_object(self, *, Bucket, Key):
        self.calls.append(("get", Bucket, Key))
        return {"Body": io.BytesIO(self.data)}


def test_s3_adapter_downloads_allowlisted_object_atomically_and_hashes_it(tmp_path):
    data = b"sample media bytes"
    client = FakeS3(data)
    adapter = S3ObjectAdapter(client, ["archive-bucket"], tmp_path / "incoming")

    result = adapter.download("archive-bucket", "interviews/episode.mp4")

    destination = tmp_path / "incoming" / result["path"].split("/")[-1]
    assert destination.read_bytes() == data
    assert result["bucket"] == "archive-bucket"
    assert result["key"] == "interviews/episode.mp4"
    assert result["size_bytes"] == len(data)
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert result["media_extension"] == ".mp4"
    assert [call[0] for call in client.calls] == ["head", "get"]
    assert not list((tmp_path / "incoming").glob("*.part"))


def test_s3_adapter_rejects_unapproved_bucket_before_cloud_access(tmp_path):
    client = FakeS3()
    adapter = S3ObjectAdapter(client, ["approved-bucket"], tmp_path)

    with pytest.raises(CloudIngestionError, match="allowlist"):
        adapter.download("other-bucket", "file.mp4")

    assert client.calls == []


def test_s3_adapter_rejects_oversized_and_non_media_objects(tmp_path):
    client = FakeS3(b"123456", "text/html")
    adapter = S3ObjectAdapter(client, ["archive-bucket"], tmp_path, max_bytes=5)

    with pytest.raises(CloudIngestionError, match="size limit"):
        adapter.download("archive-bucket", "file.mp4")

    client = FakeS3(b"html", "text/html")
    adapter = S3ObjectAdapter(client, ["archive-bucket"], tmp_path)
    with pytest.raises(CloudIngestionError, match="non-media"):
        adapter.download("archive-bucket", "file.mp4")


def test_s3_adapter_rejects_truncated_download_and_removes_partial_file(tmp_path):
    class TruncatedS3(FakeS3):
        def head_object(self, *, Bucket, Key):
            return {"ContentLength": len(self.data) + 1, "ContentType": "video/mp4"}

    client = TruncatedS3(b"short")
    adapter = S3ObjectAdapter(client, ["archive-bucket"], tmp_path)

    with pytest.raises(CloudIngestionError, match="truncated"):
        adapter.download("archive-bucket", "file.mp4")

    assert not list(tmp_path.glob("*.mp4"))
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("key", ["", "/absolute.mp4", "x" * 1025, "bad\x00key.mp4"])
def test_s3_adapter_rejects_invalid_object_keys(tmp_path, key):
    adapter = S3ObjectAdapter(FakeS3(), ["archive-bucket"], tmp_path)
    with pytest.raises(CloudIngestionError, match="key"):
        adapter.download("archive-bucket", key)


def test_s3_adapter_validates_constructor_configuration(tmp_path):
    with pytest.raises(ValueError, match="allow"):
        S3ObjectAdapter(FakeS3(), [], tmp_path)
    with pytest.raises(ValueError, match="positive"):
        S3ObjectAdapter(FakeS3(), ["archive-bucket"], tmp_path, max_bytes=0)
