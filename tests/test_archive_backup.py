import hashlib
import json
import sqlite3
import zipfile

import pytest

from src.media.archive_backup import ArchiveBackup


def test_backup_verify_and_restore_round_trip_including_sqlite_snapshot(tmp_path):
    base = tmp_path / "application"
    (base / "data" / "videos").mkdir(parents=True)
    (base / "data" / "database").mkdir(parents=True)
    (base / "exports" / "clips").mkdir(parents=True)
    (base / "exports" / "backups").mkdir(parents=True)

    video = base / "data" / "videos" / "interview.mp4"
    video.write_bytes(b"source video bytes")
    clip = base / "exports" / "clips" / "clip.mp4"
    clip.write_bytes(b"clip bytes")
    (base / "data" / "transcripts.json").write_text(
        '{"segments": []}', encoding="utf-8"
    )
    (base / "data" / "transcripts.partial.tmp").write_text(
        "incomplete", encoding="utf-8"
    )
    (base / "exports" / "backups" / "older-backup.zip").write_bytes(b"old backup")

    database = base / "data" / "database" / "videos.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE sample (value TEXT)")
    connection.execute("INSERT INTO sample VALUES ('committed in WAL')")
    connection.commit()
    connection.close()

    backup_path = base / "exports" / "backups" / "snapshot.zip"
    manager = ArchiveBackup(base)
    created = manager.create_backup(backup_path)

    assert created["file_count"] == 4
    manifest = manager.verify_backup(backup_path)
    names = {item["path"] for item in manifest["files"]}
    assert "data/videos/interview.mp4" in names
    assert "data/database/videos.db" in names
    assert "exports/clips/clip.mp4" in names
    assert "data/transcripts.json" in names
    assert all("older-backup" not in name for name in names)
    assert all("partial.tmp" not in name for name in names)

    restored = manager.restore_backup(backup_path, tmp_path / "restored")
    assert restored["file_count"] == created["file_count"]
    assert (tmp_path / "restored" / "data" / "videos" / "interview.mp4").read_bytes() == b"source video bytes"
    assert (tmp_path / "restored" / "exports" / "clips" / "clip.mp4").read_bytes() == b"clip bytes"

    restored_db = sqlite3.connect(
        tmp_path / "restored" / "data" / "database" / "videos.db"
    )
    try:
        assert restored_db.execute("SELECT value FROM sample").fetchone()[0] == "committed in WAL"
    finally:
        restored_db.close()


def test_backup_skips_symlinks_and_external_files(tmp_path):
    base = tmp_path / "application"
    data = base / "data"
    data.mkdir(parents=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("not part of archive", encoding="utf-8")
    try:
        (data / "external-link.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not available on this platform.")

    backup = ArchiveBackup(base).create_backup(
        base / "exports" / "backups" / "safe.zip"
    )
    manifest = ArchiveBackup.verify_backup(backup["backup_path"])

    assert manifest["files"] == []


def test_empty_archive_can_be_backed_up_and_restored(tmp_path):
    base = tmp_path / "application"
    base.mkdir()
    manager = ArchiveBackup(base)
    output = base / "empty.zip"

    result = manager.create_backup(output)
    manifest = manager.verify_backup(output)
    restored = manager.restore_backup(output, tmp_path / "empty-restore")

    assert result["file_count"] == 0
    assert manifest["files"] == []
    assert restored["file_count"] == 0


def test_backup_refuses_to_overwrite_existing_output(tmp_path):
    base = tmp_path / "application"
    base.mkdir()
    output = base / "backup.zip"
    output.write_bytes(b"keep existing")

    with pytest.raises(FileExistsError):
        ArchiveBackup(base).create_backup(output)

    assert output.read_bytes() == b"keep existing"


def test_restore_refuses_to_overwrite_existing_target(tmp_path):
    base = tmp_path / "application"
    (base / "data").mkdir(parents=True)
    (base / "data" / "file.txt").write_text("value", encoding="utf-8")
    backup = base / "backup.zip"
    ArchiveBackup(base).create_backup(backup)

    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        ArchiveBackup.restore_backup(backup, target)

    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_verifier_rejects_checksum_mismatch(tmp_path):
    backup = tmp_path / "bad.zip"
    original = b"expected content"
    manifest = {
        "format_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "files": [{
            "path": "data/file.txt",
            "size_bytes": len(original),
            "sha256": hashlib.sha256(original).hexdigest(),
        }],
    }
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("data/file.txt", b"tampered content")
        archive.writestr("manifest.json", json.dumps(manifest))

    with pytest.raises(ValueError, match="size mismatch|checksum mismatch"):
        ArchiveBackup.verify_backup(backup)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.txt",
        "data/../../outside.txt",
        "/data/file.txt",
        "C:\\data\\file.txt",
        "secrets/passwords.txt",
        "data/drive:stream.txt",
        "data/CON.txt",
        "data/file.",
        "data//nested.txt",
    ],
)
def test_verifier_rejects_unsafe_manifest_paths(tmp_path, unsafe_path):
    backup = tmp_path / "unsafe.zip"
    manifest = {
        "format_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "files": [{
            "path": unsafe_path,
            "size_bytes": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }],
    }
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))

    with pytest.raises(ValueError, match="path"):
        ArchiveBackup.verify_backup(backup)


def test_verifier_rejects_unlisted_zip_entries(tmp_path):
    backup = tmp_path / "unexpected.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "format_version": 1,
            "created_at": "2026-01-01T00:00:00+00:00",
            "files": [],
        }))
        archive.writestr("data/extra.txt", "unexpected")

    with pytest.raises(ValueError, match="unexpected"):
        ArchiveBackup.verify_backup(backup)


def test_restore_cleans_staging_directory_after_verification_failure(tmp_path):
    backup = tmp_path / "tampered.zip"
    manifest = {
        "format_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "files": [{
            "path": "data/file.txt",
            "size_bytes": 3,
            "sha256": hashlib.sha256(b"abc").hexdigest(),
        }],
    }
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("data/file.txt", b"xyz")
        archive.writestr("manifest.json", json.dumps(manifest))

    target = tmp_path / "restored"
    with pytest.raises(ValueError):
        ArchiveBackup.restore_backup(backup, target)

    assert not target.exists()
    assert not list(tmp_path.glob(".archive-restore-*"))


def test_verifier_rejects_duplicate_manifest_paths(tmp_path):
    backup = tmp_path / "duplicates.zip"
    item = {
        "path": "data/file.txt",
        "size_bytes": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
    }
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("data/file.txt", b"")
        archive.writestr("manifest.json", json.dumps({
            "format_version": 1,
            "created_at": "2026-01-01T00:00:00+00:00",
            "files": [item, item],
        }))

    with pytest.raises(ValueError, match="duplicate"):
        ArchiveBackup.verify_backup(backup)



def test_verifier_rejects_symbolic_link_entries(tmp_path):
    backup = tmp_path / "symlink.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        info = zipfile.ZipInfo("data/link.txt")
        info.create_system = 3
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, b"target")
        manifest = {
            "format_version": 1,
            "created_at": "2026-01-01T00:00:00+00:00",
            "files": [{
                "path": "data/link.txt",
                "size_bytes": 6,
                "sha256": hashlib.sha256(b"target").hexdigest(),
            }],
        }
        archive.writestr("manifest.json", json.dumps(manifest))

    with pytest.raises(ValueError, match="Symbolic links"):
        ArchiveBackup.verify_backup(backup)


def test_verifier_rejects_boolean_format_version(tmp_path):
    backup = tmp_path / "bad-version.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "format_version": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "files": [],
        }))

    with pytest.raises(ValueError, match="manifest"):
        ArchiveBackup.verify_backup(backup)
