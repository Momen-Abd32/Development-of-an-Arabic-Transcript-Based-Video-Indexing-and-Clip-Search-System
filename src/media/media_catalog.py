
import json
import os
import re
import tempfile
import errno
import time

from contextlib import contextmanager
from functools import wraps
from datetime import date, datetime, timezone
from pathlib import Path

from src.media.audit_log import AuditLog


@contextmanager
def _catalog_file_lock(catalog_path: Path):
    """Serialize catalog reads and read-modify-write operations across processes."""
    lock_path = catalog_path.with_name(catalog_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()

        lock_file.seek(0)

        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(
                        lock_file.fileno(),
                        msvcrt.LK_NBLCK,
                        1,
                    )
                    break
                except OSError as exc:
                    if (
                        exc.errno not in {
                            errno.EACCES,
                            errno.EAGAIN,
                            errno.EDEADLK,
                        }
                        and getattr(exc, "winerror", None) != 33
                    ):
                        raise
                    time.sleep(0.05)

            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(
                    lock_file.fileno(),
                    msvcrt.LK_UNLCK,
                    1,
                )
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _catalog_locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with _catalog_file_lock(self.catalog_path):
            return method(self, *args, **kwargs)

    return wrapper


class MediaCatalog:
    """Persist metadata that maps media identifiers to source files."""

    VALID_TYPES = {"audio", "video"}
    VALID_STATUSES = {"uploaded", "processing", "transcribed", "failed"}

    def __init__(
        self,
        catalog_path="data/database/media_catalog.json",
        audit_database_path="data/database/processing_queue.db",
    ):
        self.catalog_path = Path(catalog_path)
        self.audit_database_path = Path(audit_database_path)

    def _record_audit(
        self,
        action: str,
        media_id: str,
        before: dict | None,
        after: dict,
        actor: str = "system",
    ) -> None:
        audit = AuditLog(self.audit_database_path)
        try:
            audit.record(
                action=action,
                entity_type="media",
                entity_id=media_id,
                actor=actor,
                details={"before": before, "after": after},
            )
        finally:
            audit.close()

    def _load(self) -> list[dict]:
        if not self.catalog_path.exists():
            return []

        data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Media catalog must contain a JSON list.")

        seen_ids = set()
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(
                    f"Media catalog item {index} must be an object."
                )

            required = {
                "media_id",
                "media_type",
                "source_name",
                "stored_path",
                "status",
                "created_at",
            }
            if not required.issubset(item):
                raise ValueError(
                    f"Media catalog item {index} is missing required fields."
                )

            self._validate_media(
                item["media_id"],
                item["media_type"],
                item["source_name"],
                item["stored_path"],
                item["status"],
            )

            if (
                not isinstance(item["created_at"], str)
                or not item["created_at"].strip()
            ):
                raise ValueError(
                    f"Media catalog item {index} has an invalid creation date."
                )

            if "error" in item and not isinstance(item["error"], str):
                raise ValueError(
                    f"Media catalog item {index} has an invalid error message."
                )

            if "collection" in item and (
                item["collection"] is not None
                and (
                    not isinstance(item["collection"], str)
                    or not item["collection"].strip()
                )
            ):
                raise ValueError(
                    f"Media catalog item {index} has an invalid collection."
                )

            if "tags" in item and (
                not isinstance(item["tags"], list)
                or any(
                    not isinstance(tag, str) or not tag.strip()
                    for tag in item["tags"]
                )
                or len({tag.casefold() for tag in item["tags"]})
                != len(item["tags"])
            ):
                raise ValueError(
                    f"Media catalog item {index} has invalid tags."
                )

            if item["media_id"] in seen_ids:
                raise ValueError(
                    f"Media catalog contains duplicate ID: {item['media_id']}"
                )

            seen_ids.add(item["media_id"])

        return data

    def _save(self, items: list[dict]) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.catalog_path.parent,
                prefix=f".{self.catalog_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(items, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, self.catalog_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _validate_media(
        media_id: str,
        media_type: str,
        source_name: str,
        stored_path: str,
        status: str,
    ) -> None:
        if not isinstance(media_id, str) or not re.fullmatch(
            r"[0-9a-f]{64}", media_id
        ):
            raise ValueError("Media ID must be a lowercase SHA-256 hash.")

        if (
            not isinstance(media_type, str)
            or media_type not in MediaCatalog.VALID_TYPES
        ):
            raise ValueError("Media type must be 'audio' or 'video'.")

        if not isinstance(source_name, str) or not source_name.strip():
            raise ValueError("Source name cannot be empty.")

        if not isinstance(stored_path, str) or not stored_path.strip():
            raise ValueError("Stored path cannot be empty.")

        if not isinstance(status, str) or status not in MediaCatalog.VALID_STATUSES:
            raise ValueError("Invalid media processing status.")

    @_catalog_locked
    def register_media(
        self,
        media_id: str,
        media_type: str,
        source_name: str,
        stored_path: str,
        status: str = "uploaded",
        actor: str = "system",
    ) -> dict:
        self._validate_media(
            media_id,
            media_type,
            source_name,
            stored_path,
            status,
        )

        items = self._load()
        existing = next(
            (item for item in items if item["media_id"] == media_id),
            None,
        )

        previous = dict(existing) if existing is not None else None
        if existing is not None:
            existing.update({
                "media_type": media_type,
                "source_name": source_name,
                "stored_path": stored_path,
                "status": status,
            })
            existing.pop("error", None)
            record = existing
        else:
            record = {
                "media_id": media_id,
                "media_type": media_type,
                "source_name": source_name,
                "stored_path": stored_path,
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            items.append(record)

        self._save(items)
        self._record_audit(
            "media_registered" if existing is None else "media_record_updated",
            media_id,
            previous,
            dict(record),
            actor,
        )
        return dict(record)

    @_catalog_locked
    def update_status(
        self,
        media_id: str,
        status: str,
        error: str | None = None,
        actor: str = "system",
    ) -> dict:
        if not isinstance(media_id, str) or not media_id.strip():
            raise ValueError("Media ID cannot be empty.")

        if not isinstance(status, str) or status not in self.VALID_STATUSES:
            raise ValueError("Invalid media processing status.")

        if error is not None and not isinstance(error, str):
            raise TypeError("Error message must be a string or None.")

        items = self._load()
        record = next(
            (item for item in items if item["media_id"] == media_id),
            None,
        )
        if record is None:
            raise KeyError(f"Media not found in catalog: {media_id}")

        before = dict(record)
        record["status"] = status
        if error:
            record["error"] = error
        else:
            record.pop("error", None)

        self._save(items)
        self._record_audit(
            "media_status_updated",
            media_id,
            before,
            dict(record),
            actor,
        )
        return dict(record)

    @_catalog_locked
    def get_by_id(self, media_id: str) -> dict | None:
        return next(
            (
                dict(item)
                for item in self._load()
                if item["media_id"] == media_id
            ),
            None,
        )

    @_catalog_locked
    def get_all(self) -> list[dict]:
        return [dict(item) for item in self._load()]

    @staticmethod
    def _normalize_tags(tags: list[str]) -> list[str]:
        if not isinstance(tags, list):
            raise TypeError("Tags must be provided as a list of strings.")

        normalized = []
        seen = set()
        for tag in tags:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError("Tags must be non-empty strings.")

            value = tag.strip()
            key = value.casefold()
            if key not in seen:
                normalized.append(value)
                seen.add(key)

        return normalized

    @_catalog_locked
    def update_archive_metadata(
        self,
        media_id: str,
        collection: str | None = None,
        tags: list[str] | None = None,
        actor: str = "system",
    ) -> dict:
        """Update optional collection and tags without changing legacy fields."""
        if not isinstance(media_id, str) or not media_id.strip():
            raise ValueError("Media ID cannot be empty.")

        if collection is not None:
            if not isinstance(collection, str):
                raise TypeError("Collection must be a string or None.")
            collection = collection.strip() or None

        normalized_tags = None if tags is None else self._normalize_tags(tags)

        items = self._load()
        record = next(
            (item for item in items if item["media_id"] == media_id),
            None,
        )
        if record is None:
            raise KeyError(f"Media not found in catalog: {media_id}")

        before = dict(record)
        if collection is None:
            record.pop("collection", None)
        else:
            record["collection"] = collection

        if normalized_tags is None:
            record.pop("tags", None)
        else:
            record["tags"] = normalized_tags

        self._save(items)
        self._record_audit(
            "media_metadata_updated",
            media_id,
            before,
            dict(record),
            actor,
        )
        return dict(record)

    @_catalog_locked
    def get_collections(self) -> list[str]:
        return sorted(
            {
                item["collection"]
                for item in self._load()
                if item.get("collection")
            },
            key=str.casefold,
        )

    @_catalog_locked
    def get_all_tags(self) -> list[str]:
        tags = {}
        for item in self._load():
            for tag in item.get("tags", []):
                tags.setdefault(tag.casefold(), tag)

        return sorted(tags.values(), key=str.casefold)

    @_catalog_locked
    def filter_media(
        self,
        collection: str | None = None,
        tags: list[str] | None = None,
        media_type: str | None = None,
        source_contains: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """Filter catalog records by organization, source, type, and added date."""
        if collection is not None and (
            not isinstance(collection, str) or not collection.strip()
        ):
            raise ValueError("Collection filter must be a non-empty string.")

        if media_type is not None and media_type not in self.VALID_TYPES:
            raise ValueError("Media type filter must be 'audio' or 'video'.")

        if source_contains is not None and not isinstance(source_contains, str):
            raise TypeError("Source filter must be a string or None.")

        parsed_start = date.fromisoformat(start_date) if start_date else None
        parsed_end = date.fromisoformat(end_date) if end_date else None

        if parsed_start and parsed_end and parsed_start > parsed_end:
            raise ValueError("Start date cannot be after end date.")

        required_tags = self._normalize_tags(tags or [])
        records = self._load()
        filtered = []

        for item in records:
            if collection is not None and (
                item.get("collection", "").casefold()
                != collection.strip().casefold()
            ):
                continue

            if media_type is not None and item["media_type"] != media_type:
                continue

            if (
                source_contains
                and source_contains.casefold()
                not in item["source_name"].casefold()
            ):
                continue

            created = item["created_at"][:10]
            if parsed_start and created < parsed_start.isoformat():
                continue

            if parsed_end and created > parsed_end.isoformat():
                continue

            item_tags = {tag.casefold() for tag in item.get("tags", [])}
            if not all(tag.casefold() in item_tags for tag in required_tags):
                continue

            filtered.append(dict(item))

        return filtered
