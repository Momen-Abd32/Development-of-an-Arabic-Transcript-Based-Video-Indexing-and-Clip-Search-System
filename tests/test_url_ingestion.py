import hashlib
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError

import pytest

from src.media.url_ingestion import RemoteURLAdapter, URLIngestionError


PUBLIC_IPS = ["93.184.216.34"]
ALLOWED = ["media.example.com"]


class FakeResponse:
    def __init__(self, body=b"media bytes", *, content_type="video/mp4", status=200, headers=None):
        self.body = BytesIO(body)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.closed = False

    def getcode(self):
        return self.status

    def read(self, size=-1):
        return self.body.read(size)

    def close(self):
        self.closed = True


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_adapter(tmp_path, opener, **kwargs):
    return RemoteURLAdapter(
        ALLOWED,
        tmp_path / "remote",
        resolver=lambda host, port: PUBLIC_IPS,
        opener_factory=lambda: opener,
        **kwargs,
    )


def test_downloads_allowlisted_https_media_and_returns_checksum(tmp_path):
    body = b"trusted media payload"
    response = FakeResponse(body)
    opener = FakeOpener([response])
    adapter = make_adapter(tmp_path, opener)

    result = adapter.download("https://media.example.com/archive/interview.mp4?token=secret")

    path = __import__("pathlib").Path(result["path"])
    assert path.is_file()
    assert path.read_bytes() == body
    assert result["source_host"] == "media.example.com"
    assert result["media_extension"] == ".mp4"
    assert result["size_bytes"] == len(body)
    assert result["sha256"] == hashlib.sha256(body).hexdigest()
    assert "secret" not in result["path"]
    assert response.closed is True
    assert opener.calls[0][1] == 30


def test_infers_supported_extension_from_content_type(tmp_path):
    response = FakeResponse(
        b"audio payload",
        content_type="audio/mpeg",
    )
    adapter = make_adapter(tmp_path, FakeOpener([response]))

    result = adapter.download("https://media.example.com/download?id=42")

    assert result["media_extension"] == ".mp3"
    assert result["path"].endswith(".mp3")


def test_follows_redirect_only_after_validating_redirect_destination(tmp_path):
    redirect_headers = Message()
    redirect_headers["Location"] = "/files/final.mp4"
    redirect = HTTPError(
        "https://media.example.com/start",
        302,
        "Found",
        redirect_headers,
        None,
    )
    response = FakeResponse(b"redirected media")
    opener = FakeOpener([redirect, response])
    adapter = make_adapter(tmp_path, opener)

    result = adapter.download("https://media.example.com/start")

    assert result["media_extension"] == ".mp4"
    assert len(opener.calls) == 2
    assert response.closed is True


def test_rejects_redirect_to_non_allowlisted_host_before_second_request(tmp_path):
    redirect_headers = Message()
    redirect_headers["Location"] = "https://evil.example.net/file.mp4"
    redirect = HTTPError(
        "https://media.example.com/start",
        302,
        "Found",
        redirect_headers,
        None,
    )
    opener = FakeOpener([redirect])
    adapter = make_adapter(tmp_path, opener)

    with pytest.raises(URLIngestionError, match="not allowlisted"):
        adapter.download("https://media.example.com/start")
    assert len(opener.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://media.example.com/file.mp4",
        "https://user:password@media.example.com/file.mp4",
        "https://media.example.com:8443/file.mp4",
        "https://untrusted.example.net/file.mp4",
        "",
    ],
)
def test_rejects_unsafe_or_unapproved_urls_before_network_access(tmp_path, url):
    opener = FakeOpener([])
    adapter = make_adapter(tmp_path, opener)

    with pytest.raises(URLIngestionError):
        adapter.download(url)
    assert opener.calls == []


def test_rejects_dns_answers_that_are_not_public(tmp_path):
    opener = FakeOpener([])
    adapter = RemoteURLAdapter(
        ALLOWED,
        tmp_path / "remote",
        resolver=lambda host, port: ["127.0.0.1"],
        opener_factory=lambda: opener,
    )

    with pytest.raises(URLIngestionError, match="non-public"):
        adapter.download("https://media.example.com/file.mp4")
    assert opener.calls == []


def test_rejects_mixed_public_and_private_dns_answers(tmp_path):
    adapter = RemoteURLAdapter(
        ALLOWED,
        tmp_path / "remote",
        resolver=lambda host, port: ["93.184.216.34", "10.0.0.5"],
        opener_factory=lambda: FakeOpener([]),
    )

    with pytest.raises(URLIngestionError, match="non-public"):
        adapter.download("https://media.example.com/file.mp4")


def test_rejects_non_media_content_type(tmp_path):
    response = FakeResponse(
        b"<html>not media</html>",
        content_type="text/html",
    )
    adapter = make_adapter(tmp_path, FakeOpener([response]))

    with pytest.raises(URLIngestionError, match="non-media"):
        adapter.download("https://media.example.com/disguised.mp4")
    assert response.closed is True


def test_rejects_content_length_over_limit_before_writing(tmp_path):
    response = FakeResponse(
        b"too large",
        headers={"Content-Length": "1000"},
    )
    adapter = make_adapter(
        tmp_path,
        FakeOpener([response]),
        max_bytes=10,
    )

    with pytest.raises(URLIngestionError, match="size limit"):
        adapter.download("https://media.example.com/file.mp4")
    assert response.closed is True
    assert not list((tmp_path / "remote").glob("*"))


def test_enforces_streamed_size_limit_and_removes_partial_file(tmp_path):
    response = FakeResponse(b"x" * 40)
    adapter = make_adapter(
        tmp_path,
        FakeOpener([response]),
        max_bytes=10,
    )

    with pytest.raises(URLIngestionError, match="size limit"):
        adapter.download("https://media.example.com/file.mp4")

    assert response.closed is True
    assert list((tmp_path / "remote").glob("*.part")) == []
    assert list((tmp_path / "remote").glob("*.mp4")) == []


def test_rejects_truncated_and_empty_downloads(tmp_path):
    truncated = FakeResponse(b"abc", headers={"Content-Length": "10"})
    adapter = make_adapter(tmp_path, FakeOpener([truncated]))
    with pytest.raises(URLIngestionError, match="truncated"):
        adapter.download("https://media.example.com/file.mp4")

    empty = FakeResponse(b"")
    adapter = make_adapter(tmp_path, FakeOpener([empty]))
    with pytest.raises(URLIngestionError, match="empty"):
        adapter.download("https://media.example.com/file.mp4")


def test_rejects_redirect_limit_exceeded(tmp_path):
    headers = Message()
    headers["Location"] = "/again.mp4"
    redirect = HTTPError(
        "https://media.example.com/start",
        302,
        "Found",
        headers,
        None,
    )
    adapter = make_adapter(
        tmp_path,
        FakeOpener([redirect, redirect]),
        max_redirects=1,
    )

    with pytest.raises(URLIngestionError, match="redirect limit"):
        adapter.download("https://media.example.com/start")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allowed_hosts": []},
        {"allowed_hosts": ["*"]},
        {"allowed_hosts": ["media.example.com"], "max_bytes": 0},
        {"allowed_hosts": ["media.example.com"], "timeout_seconds": float("nan")},
        {"allowed_hosts": ["media.example.com"], "timeout_seconds": float("inf")},
        {"allowed_hosts": ["media.example.com"], "max_redirects": -1},
    ],
)
def test_validates_adapter_configuration(tmp_path, kwargs):
    allowed_hosts = kwargs.pop("allowed_hosts", ALLOWED)
    with pytest.raises(ValueError):
        RemoteURLAdapter(
            allowed_hosts,
            tmp_path / "remote",
            **kwargs,
        )
