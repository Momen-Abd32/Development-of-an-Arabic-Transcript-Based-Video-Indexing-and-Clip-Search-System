"""Optional S3-compatible object storage ingestion for archive media."""
from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit


class CloudIngestionError(ValueError):
    """Raised when a cloud object is not an approved media source."""


class S3ObjectAdapter:
    """Download allowlisted S3 objects atomically for the normal import queue.

    Credentials and endpoint configuration are supplied by the operator through
    boto3's standard profile/environment chain. Object bytes are never treated
    as filesystem paths.
    """

    SUPPORTED_EXTENSIONS = {
        ".mp4", ".mov", ".mkv", ".webm", ".avi",
        ".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a",
    }
    MIME_EXTENSIONS = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-matroska": ".mkv",
        "video/webm": ".webm",
        "video/x-msvideo": ".avi",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/flac": ".flac",
        "audio/ogg": ".ogg",
        "audio/aac": ".aac",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
    }
    CHUNK_SIZE = 1024 * 1024

    def __init__(
        self,
        client,
        allowed_buckets: list[str] | tuple[str, ...],
        download_directory: str | Path = "data/incoming/cloud",
        *,
        max_bytes: int = 2 * 1024 * 1024 * 1024,
    ):
        if not isinstance(allowed_buckets, (list, tuple)) or not allowed_buckets:
            raise ValueError("At least one exact allowed bucket is required.")
        buckets = set()
        for bucket in allowed_buckets:
            if not isinstance(bucket, str) or not bucket.strip():
                raise ValueError("Allowed bucket names must be non-empty strings.")
            value = bucket.strip()
            if value != bucket or "/" in value or "\\" in value:
                raise ValueError("Allowed bucket names must be exact bucket identifiers.")
            buckets.add(value)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("Maximum object size must be a positive integer.")
        if client is None or not callable(getattr(client, "head_object", None)) or not callable(
            getattr(client, "get_object", None)
        ):
            raise TypeError("A compatible object-storage client is required.")

        self.client = client
        self.allowed_buckets = buckets
        self.download_directory = Path(download_directory).expanduser()
        self.max_bytes = max_bytes

    @classmethod
    def from_boto3(
        cls,
        allowed_buckets: list[str] | tuple[str, ...],
        download_directory: str | Path = "data/incoming/cloud",
        *,
        max_bytes: int = 2 * 1024 * 1024 * 1024,
        profile_name: str | None = None,
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> "S3ObjectAdapter":
        try:
            import boto3
        except ImportError as error:
            raise RuntimeError(
                "S3 ingestion requires the optional requirements-cloud.txt dependencies."
            ) from error

        session = boto3.Session(
            profile_name=profile_name or None,
            region_name=region_name or None,
        )
        client = session.client("s3", endpoint_url=endpoint_url or None)
        return cls(
            client,
            allowed_buckets,
            download_directory,
            max_bytes=max_bytes,
        )

    def _extension(self, key: str, content_type: str) -> str:
        suffix = Path(key).suffix.lower()
        if suffix in self.SUPPORTED_EXTENSIONS:
            if content_type and not (
                content_type.startswith(("audio/", "video/"))
                or content_type == "application/octet-stream"
            ):
                raise CloudIngestionError(
                    f"Cloud object has a non-media content type: {content_type}"
                )
            return suffix
        extension = self.MIME_EXTENSIONS.get(content_type)
        if extension is None:
            extension = mimetypes.guess_extension(content_type) if content_type else None
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise CloudIngestionError(
                f"Could not determine a supported media extension for {content_type or 'unknown content'}."
            )
        return extension

    def download(self, bucket: str, key: str) -> dict:
        if not isinstance(bucket, str) or bucket not in self.allowed_buckets:
            raise CloudIngestionError("Cloud bucket is not in the exact operator allowlist.")
        if not isinstance(key, str) or not key.strip() or key.startswith("/"):
            raise CloudIngestionError("Cloud object key must be a non-empty relative object key.")
        if len(key) > 1024 or "\x00" in key:
            raise CloudIngestionError("Cloud object key is invalid.")

        metadata = self.client.head_object(Bucket=bucket, Key=key)
        expected_size = metadata.get("ContentLength")
        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size <= 0
        ):
            raise CloudIngestionError("Cloud object must have a positive ContentLength.")
        if expected_size > self.max_bytes:
            raise CloudIngestionError("Cloud object exceeds the configured size limit.")

        content_type = str(metadata.get("ContentType", "")).split(";", 1)[0].strip().lower()
        extension = self._extension(key, content_type)
        self.download_directory.mkdir(parents=True, exist_ok=True)
        object_id = uuid.uuid4().hex
        destination = self.download_directory / f"{object_id}{extension}"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{object_id}.",
            suffix=".part",
            dir=self.download_directory,
        )
        response = None
        digest = hashlib.sha256()
        total = 0
        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
            body = response.get("Body")
            if body is None or not callable(getattr(body, "read", None)):
                raise CloudIngestionError("Cloud object response has no readable body.")
            with os.fdopen(descriptor, "wb") as output:
                while True:
                    chunk = body.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_bytes or total > expected_size:
                        raise CloudIngestionError("Cloud object exceeded its declared size.")
                    output.write(chunk)
                    digest.update(chunk)
            if total != expected_size:
                raise CloudIngestionError("Cloud object download was truncated.")
            os.replace(temporary_name, destination)
        except Exception:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
            raise
        finally:
            if response is not None:
                body = response.get("Body")
                close = getattr(body, "close", None)
                if callable(close):
                    close()

        return {
            "path": str(destination),
            "bucket": bucket,
            "key": key,
            "size_bytes": total,
            "sha256": digest.hexdigest(),
            "media_extension": extension,
        }
