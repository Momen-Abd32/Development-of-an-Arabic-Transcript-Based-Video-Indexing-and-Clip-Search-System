"""Secure-by-default downloader for direct media URLs on allowlisted hosts."""
from __future__ import annotations

import hashlib
import ipaddress
import math
import mimetypes
import os
import socket
import tempfile
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)


class URLIngestionError(ValueError):
    """Raised when a remote media URL cannot be safely imported."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class RemoteURLAdapter:
    """Download direct media files from explicitly allowlisted public hosts.

    Redirects are followed manually so every destination is validated. The
    opener disables environment proxies, and DNS answers must all be globally
    routable. Configure only domains controlled by the archive operator.
    """

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
    REDIRECT_CODES = {301, 302, 303, 307, 308}
    CHUNK_SIZE = 1024 * 1024

    def __init__(
        self,
        allowed_hosts: list[str] | tuple[str, ...],
        download_directory: str | Path = "data/incoming/remote",
        *,
        max_bytes: int = 2 * 1024 * 1024 * 1024,
        timeout_seconds: float = 30,
        max_redirects: int = 3,
        resolver=None,
        opener_factory=None,
    ):
        if not isinstance(allowed_hosts, (list, tuple)) or not allowed_hosts:
            raise ValueError("At least one explicitly allowed host is required.")
        normalized_hosts = set()
        for host in allowed_hosts:
            if not isinstance(host, str) or not host.strip():
                raise ValueError("Allowed hosts must be non-empty host names.")
            value = host.strip().encode("idna").decode("ascii").lower()
            if "*" in value or "/" in value or ":" in value:
                raise ValueError("Allowed hosts must be exact DNS names or IP addresses.")
            normalized_hosts.add(value)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("Maximum download size must be a positive integer.")
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise ValueError("Timeout must be a finite positive number.")
        try:
            timeout_value = float(timeout_seconds)
        except (OverflowError, ValueError) as error:
            raise ValueError("Timeout must be a finite positive number.") from error
        if not math.isfinite(timeout_value) or timeout_value <= 0:
            raise ValueError("Timeout must be a finite positive number.")
        if isinstance(max_redirects, bool) or not isinstance(max_redirects, int) or max_redirects < 0:
            raise ValueError("Maximum redirects must be a non-negative integer.")

        self.allowed_hosts = normalized_hosts
        self.download_directory = Path(download_directory).expanduser()
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_value
        self.max_redirects = max_redirects
        self.resolver = resolver or self._resolve_host
        self.opener_factory = opener_factory or self._build_opener

    @staticmethod
    def _resolve_host(host: str, port: int) -> list[str]:
        try:
            return sorted({
                item[4][0]
                for item in socket.getaddrinfo(
                    host,
                    port,
                    type=socket.SOCK_STREAM,
                )
            })
        except OSError as error:
            raise URLIngestionError(f"Could not resolve media host: {host}") from error

    @staticmethod
    def _build_opener():
        return build_opener(
            ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def _validate_url(self, url: str) -> tuple[str, str]:
        if not isinstance(url, str) or not url.strip():
            raise URLIngestionError("Media URL must be a non-empty string.")
        clean_url, _fragment = urldefrag(url.strip())
        try:
            parsed = urlsplit(clean_url)
            host = parsed.hostname
            port = parsed.port
        except ValueError as error:
            raise URLIngestionError("Media URL is malformed.") from error

        if parsed.scheme.lower() != "https":
            raise URLIngestionError("Only HTTPS media URLs are accepted.")
        if not host or parsed.username is not None or parsed.password is not None:
            raise URLIngestionError("Media URL must not contain credentials.")
        if port not in (None, 443):
            raise URLIngestionError("Only the standard HTTPS port is accepted.")

        normalized_host = host.encode("idna").decode("ascii").lower()
        if normalized_host not in self.allowed_hosts:
            raise URLIngestionError(
                f"Media host is not allowlisted: {normalized_host}"
            )

        addresses = self.resolver(normalized_host, 443)
        if not addresses:
            raise URLIngestionError("Media host did not resolve to an IP address.")
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as error:
                raise URLIngestionError("Media host resolved to an invalid IP address.") from error
            if not ip.is_global:
                raise URLIngestionError(
                    "Media host resolved to a non-public IP address."
                )
        return clean_url, normalized_host

    def _extension_for(self, url: str, content_type: str) -> str:
        suffix = Path(urlsplit(url).path).suffix.lower()
        if suffix in {
            ".mp4", ".mov", ".mkv", ".webm", ".avi",
            ".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a",
        }:
            if content_type and not (
                content_type.startswith(("audio/", "video/"))
                or content_type == "application/octet-stream"
            ):
                raise URLIngestionError(
                    f"URL returned a non-media content type: {content_type}"
                )
            return suffix

        inferred = self.MIME_EXTENSIONS.get(content_type)
        if inferred is None:
            guessed = mimetypes.guess_extension(content_type) if content_type else None
            if guessed in {
                ".mp4", ".mov", ".mkv", ".webm", ".avi",
                ".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a",
            }:
                inferred = guessed
        if inferred is None:
            raise URLIngestionError(
                f"Could not determine a supported media extension for {content_type or 'unknown content'}."
            )
        return inferred

    def download(self, url: str) -> dict:
        """Download one direct media URL atomically and return its local path."""
        current_url, host = self._validate_url(url)
        opener = self.opener_factory()
        response = None

        try:
            for redirect_count in range(self.max_redirects + 1):
                request = Request(
                    current_url,
                    headers={
                        "User-Agent": "ArabicArchiveMediaImporter/1.0",
                        "Accept": "audio/*, video/*, application/octet-stream",
                    },
                    method="GET",
                )
                try:
                    response = opener.open(
                        request,
                        timeout=self.timeout_seconds,
                    )
                except HTTPError as error:
                    if error.code not in self.REDIRECT_CODES:
                        raise URLIngestionError(
                            f"Remote server returned HTTP {error.code}."
                        ) from error
                    location = error.headers.get("Location")
                    error.close()
                    if not location or redirect_count >= self.max_redirects:
                        raise URLIngestionError("Remote URL exceeded the redirect limit.")
                    next_url = urljoin(current_url, location)
                    current_url, host = self._validate_url(next_url)
                    continue
                except (URLError, TimeoutError, OSError) as error:
                    raise URLIngestionError(f"Could not download media URL: {error}") from error

                status = response.getcode()
                if status != 200:
                    response.close()
                    raise URLIngestionError(
                        f"Remote server returned unexpected HTTP status {status}."
                    )
                headers = response.headers
                content_type = headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                extension = self._extension_for(current_url, content_type)
                content_length = headers.get("Content-Length")
                expected_size = None
                if content_length is not None:
                    try:
                        expected_size = int(content_length)
                    except ValueError as error:
                        raise URLIngestionError("Remote Content-Length is invalid.") from error
                    if expected_size < 0 or expected_size > self.max_bytes:
                        raise URLIngestionError("Remote media exceeds the configured size limit.")

                self.download_directory.mkdir(parents=True, exist_ok=True)
                file_id = uuid.uuid4().hex
                destination = self.download_directory / f"{file_id}{extension}"
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{file_id}.",
                    suffix=".part",
                    dir=self.download_directory,
                )
                digest = hashlib.sha256()
                total_bytes = 0
                try:
                    with os.fdopen(descriptor, "wb") as output:
                        while True:
                            chunk = response.read(self.CHUNK_SIZE)
                            if not chunk:
                                break
                            total_bytes += len(chunk)
                            if total_bytes > self.max_bytes:
                                raise URLIngestionError(
                                    "Remote media exceeds the configured size limit."
                                )
                            output.write(chunk)
                            digest.update(chunk)
                    if total_bytes == 0:
                        raise URLIngestionError("Remote media file is empty.")
                    if expected_size is not None and total_bytes != expected_size:
                        raise URLIngestionError("Remote media download was truncated.")
                    os.replace(temporary_name, destination)
                except Exception:
                    if os.path.exists(temporary_name):
                        os.unlink(temporary_name)
                    raise
                finally:
                    response.close()
                    response = None

                return {
                    "path": str(destination),
                    "source_host": host,
                    "size_bytes": total_bytes,
                    "sha256": digest.hexdigest(),
                    "media_extension": extension,
                }

            raise URLIngestionError("Remote URL exceeded the redirect limit.")
        finally:
            if response is not None:
                response.close()
