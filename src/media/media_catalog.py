import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class MediaCatalog:
    """Persist metadata that maps media identifiers to source files."""

    VALID_TYPES = {"audio", "video"}
    VALID_STATUSES = {"uploaded", "processing", "transcribed", "failed"}

    def __init__(self, catalog_path="data/database/media_catalog.json"):
        self.catalog_path = Path(catalog_path)

    def _load(self) -> list[dict]:
        if not self.catalog_path.exists():
            return []

        data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Media catalog must contain a JSON list.")

        for index, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"Media catalog item {index} must be an object.")
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

        if media_type not in MediaCatalog.VALID_TYPES:
            raise ValueError("Media type must be 'audio' or 'video'.")

        if not isinstance(source_name, str) or not source_name.strip():
            raise ValueError("Source name cannot be empty.")

        if not isinstance(stored_path, str) or not stored_path.strip():
            raise ValueError("Stored path cannot be empty.")

        if status not in MediaCatalog.VALID_STATUSES:
            raise ValueError("Invalid media processing status.")

    def register_media(
        self,
        media_id: str,
        media_type: str,
        source_name: str,
        stored_path: str,
        status: str = "uploaded",
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
        return dict(record)

    def update_status(
        self,
        media_id: str,
        status: str,
        error: str | None = None,
    ) -> dict:
        if status not in self.VALID_STATUSES:
            raise ValueError("Invalid media processing status.")

        items = self._load()
        record = next(
            (item for item in items if item["media_id"] == media_id),
            None,
        )
        if record is None:
            raise KeyError(f"Media not found in catalog: {media_id}")

        record["status"] = status
        if error:
            record["error"] = str(error)
        else:
            record.pop("error", None)

        self._save(items)
        return dict(record)

    def get_by_id(self, media_id: str) -> dict | None:
        return next(
            (
                dict(item)
                for item in self._load()
                if item["media_id"] == media_id
            ),
            None,
        )

    def get_all(self) -> list[dict]:
        return [dict(item) for item in self._load()]
