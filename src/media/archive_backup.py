"""Verified, restorable snapshots of the local media archive."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath


class ArchiveBackup:
    """Create and restore checksummed snapshots of data/ and exports/."""

    FORMAT_VERSION = 1
    ROOTS = ("data", "exports")
    EXCLUDED_PREFIXES = ("exports/backups/",)
    CHUNK_SIZE = 1024 * 1024

    def __init__(self, base_directory: str | Path = "."):
        self.base_directory = Path(base_directory).expanduser().resolve()

    @classmethod
    def _sha256(cls, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(cls.CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_archive_path(value: str) -> PurePosixPath:
        if not isinstance(value, str) or not value or "\\" in value:
            raise ValueError("Backup contains an invalid archive path.")
        path = PurePosixPath(value)
        windows_path = PureWindowsPath(value)
        windows_reserved = {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{number}" for number in range(1, 10)),
            *(f"LPT{number}" for number in range(1, 10)),
        }
        if (
            path.is_absolute()
            or path.as_posix() != value
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(
                ":" in part
                or part.endswith((" ", "."))
                or part.split(".", 1)[0].upper() in windows_reserved
                for part in path.parts
            )
            or not (value.startswith("data/") or value.startswith("exports/"))
        ):
            raise ValueError("Backup contains a path outside data/ or exports/.")
        return path

    @staticmethod
    def _is_temporary(path: Path) -> bool:
        name = path.name.lower()
        return (
            path.is_symlink()
            or name.startswith(".")
            or name.endswith((".tmp", ".wal", ".shm", "-wal", "-shm"))
        )

    @staticmethod
    def _snapshot_sqlite(source_path: Path, destination_path: Path) -> None:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(source_path, timeout=30)
        destination = sqlite3.connect(destination_path, timeout=30)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()

    def create_backup(self, output_path: str | Path) -> dict:
        """Create an atomic ZIP snapshot with per-file SHA-256 checksums."""
        output = Path(output_path).expanduser()
        if not output.is_absolute():
            output = self.base_directory / output
        output = output.resolve()
        if output.exists():
            raise FileExistsError(f"Backup output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)

        temporary_output = output.with_name(
            f".{output.name}.{uuid.uuid4().hex}.tmp"
        )
        manifest_files = []
        snapshot_directory = Path(
            tempfile.mkdtemp(prefix="archive-backup-")
        )

        try:
            with zipfile.ZipFile(
                temporary_output,
                mode="w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as archive:
                for root_name in self.ROOTS:
                    root = self.base_directory / root_name
                    if not root.exists():
                        continue
                    if not root.is_dir():
                        raise ValueError(f"Backup root is not a directory: {root}")

                    for source_path in sorted(
                        root.rglob("*"),
                        key=lambda item: item.as_posix().lower(),
                    ):
                        if not source_path.is_file() or self._is_temporary(source_path):
                            continue
                        relative = source_path.relative_to(
                            self.base_directory
                        ).as_posix()
                        if any(
                            relative.startswith(prefix)
                            for prefix in self.EXCLUDED_PREFIXES
                        ):
                            continue
                        if output == source_path.resolve():
                            continue
                        self._safe_archive_path(relative)

                        archive_source = source_path
                        if source_path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                            archive_source = snapshot_directory / relative
                            self._snapshot_sqlite(source_path, archive_source)

                        digest = self._sha256(archive_source)
                        size = archive_source.stat().st_size
                        archive.write(archive_source, arcname=relative)
                        manifest_files.append({
                            "path": relative,
                            "size_bytes": size,
                            "sha256": digest,
                        })

                manifest = {
                    "format_version": self.FORMAT_VERSION,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "files": manifest_files,
                }
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )

            os.replace(temporary_output, output)
            return {
                "backup_path": str(output),
                "file_count": len(manifest_files),
                "total_bytes": sum(item["size_bytes"] for item in manifest_files),
                "created_at": manifest["created_at"],
            }
        finally:
            if temporary_output.exists():
                temporary_output.unlink()
            shutil.rmtree(snapshot_directory, ignore_errors=True)

    @classmethod
    def verify_backup(cls, backup_path: str | Path) -> dict:
        """Validate manifest paths, archive membership, sizes, and checksums."""
        backup = Path(backup_path).expanduser()
        if not backup.is_file():
            raise FileNotFoundError(f"Backup file not found: {backup}")

        with zipfile.ZipFile(backup, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Backup contains duplicate archive entries.")
            if "manifest.json" not in names:
                raise ValueError("Backup manifest is missing.")

            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("Backup manifest is invalid JSON.") from error

            if (
                not isinstance(manifest, dict)
                or isinstance(manifest.get("format_version"), bool)
                or not isinstance(manifest.get("format_version"), int)
                or manifest.get("format_version") != cls.FORMAT_VERSION
                or not isinstance(manifest.get("created_at"), str)
                or not manifest.get("created_at").strip()
                or not isinstance(manifest.get("files"), list)
            ):
                raise ValueError("Unsupported or invalid backup manifest.")

            expected_names = {"manifest.json"}
            seen_paths = set()
            for item in manifest["files"]:
                if not isinstance(item, dict):
                    raise ValueError("Backup manifest file entries must be objects.")
                relative = item.get("path")
                cls._safe_archive_path(relative)
                if relative in seen_paths:
                    raise ValueError("Backup manifest contains duplicate file paths.")
                seen_paths.add(relative)
                expected_names.add(relative)

                expected_hash = item.get("sha256")
                expected_size = item.get("size_bytes")
                if (
                    not isinstance(expected_hash, str)
                    or len(expected_hash) != 64
                    or any(char not in "0123456789abcdef" for char in expected_hash)
                    or isinstance(expected_size, bool)
                    or not isinstance(expected_size, int)
                    or expected_size < 0
                ):
                    raise ValueError("Backup manifest contains invalid file metadata.")
                try:
                    info = archive.getinfo(relative)
                except KeyError as error:
                    raise ValueError(f"Backup file is missing: {relative}") from error
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError("Symbolic links are not allowed in backups.")
                if info.is_dir():
                    raise ValueError("Directory entries are not allowed in backup manifests.")
                if info.file_size != expected_size:
                    raise ValueError(f"Backup file size mismatch: {relative}")

                digest = hashlib.sha256()
                actual_size = 0
                with archive.open(info, "r") as source:
                    for chunk in iter(lambda: source.read(cls.CHUNK_SIZE), b""):
                        digest.update(chunk)
                        actual_size += len(chunk)
                if actual_size != expected_size or digest.hexdigest() != expected_hash:
                    raise ValueError(f"Backup checksum mismatch: {relative}")

            if set(names) != expected_names:
                raise ValueError("Backup contains unlisted or unexpected files.")

            return manifest

    @classmethod
    def restore_backup(
        cls,
        backup_path: str | Path,
        target_directory: str | Path,
    ) -> dict:
        """Verify and restore into a new directory without overwriting live data."""
        manifest = cls.verify_backup(backup_path)
        target = Path(target_directory).expanduser().resolve()
        if target.exists():
            raise FileExistsError(
                "Restore target must not already exist; choose a new empty path."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=".archive-restore-", dir=target.parent)
        )

        try:
            with zipfile.ZipFile(backup_path, "r") as archive:
                for item in manifest["files"]:
                    relative = cls._safe_archive_path(item["path"])
                    destination = staging.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    size = 0
                    with archive.open(item["path"], "r") as source:
                        with destination.open("wb") as output:
                            for chunk in iter(
                                lambda: source.read(cls.CHUNK_SIZE), b""
                            ):
                                output.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                    if (
                        size != item["size_bytes"]
                        or digest.hexdigest() != item["sha256"]
                    ):
                        raise ValueError(
                            f"Restored file failed verification: {item['path']}"
                        )

            os.replace(staging, target)
            return {
                "restore_directory": str(target),
                "file_count": len(manifest["files"]),
                "created_at": manifest["created_at"],
            }
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
