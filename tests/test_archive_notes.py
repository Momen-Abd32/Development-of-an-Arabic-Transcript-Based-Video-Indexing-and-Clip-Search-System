import sqlite3

import pytest

from src.media.archive_notes import ArchiveNotes
from src.media.audit_log import AuditLog


MEDIA_A = "a" * 64
MEDIA_B = "b" * 64


@pytest.fixture
def notes(tmp_path):
    manager = ArchiveNotes(tmp_path / "archive.db")
    yield manager
    manager.close()


def test_add_and_list_notes_persist_in_media_timestamp_order(notes):
    later = notes.add_note(MEDIA_A, 90.5, "راجع المقطع الأخير", author="editor-a")
    earlier = notes.add_note(MEDIA_A, 12, "تحقق من اسم المتحدث", author="editor-b")
    notes.add_note(MEDIA_B, 5, "ملاحظة لملف آخر")

    listed = notes.list_notes(MEDIA_A)

    assert [item["note_id"] for item in listed] == [
        earlier["note_id"],
        later["note_id"],
    ]
    assert listed[0]["timestamp_seconds"] == 12.0
    assert listed[0]["author"] == "editor-b"
    assert notes.list_notes(MEDIA_B)[0]["note_text"] == "ملاحظة لملف آخر"


def test_notes_survive_reopening_database(tmp_path):
    path = tmp_path / "archive.db"
    manager = ArchiveNotes(path)
    created = manager.add_note(MEDIA_A, 3.25, "راجع بداية التسجيل")
    manager.close()

    reopened = ArchiveNotes(path)
    try:
        result = reopened.list_notes(MEDIA_A)
        assert len(result) == 1
        assert result[0]["note_id"] == created["note_id"]
        assert result[0]["created_at"] == created["created_at"]
    finally:
        reopened.close()


def test_update_note_changes_text_and_timestamp_without_changing_author(notes):
    created = notes.add_note(MEDIA_A, 10, "النص الأول", author="reviewer")
    updated = notes.update_note(
        created["note_id"],
        timestamp_seconds=15.75,
        note_text="النص بعد المراجعة",
        updated_by="editor",
    )

    assert updated["timestamp_seconds"] == 15.75
    assert updated["note_text"] == "النص بعد المراجعة"
    assert updated["author"] == "reviewer"
    assert updated["updated_by"] == "editor"
    assert updated["updated_at"] >= created["updated_at"]


def test_update_note_supports_single_field_changes(notes):
    created = notes.add_note(MEDIA_A, 10, "ملاحظة")
    updated = notes.update_note(created["note_id"], note_text="ملاحظة معدلة")
    assert updated["timestamp_seconds"] == 10.0
    assert updated["note_text"] == "ملاحظة معدلة"


def test_delete_note_and_missing_delete(notes):
    created = notes.add_note(MEDIA_A, 1, "ملاحظة للحذف")
    assert notes.delete_note(created["note_id"], actor="reviewer") is True
    assert notes.list_notes(MEDIA_A) == []
    assert notes.delete_note(created["note_id"]) is False


def test_note_mutations_append_audit_events(tmp_path):
    path = tmp_path / "archive.db"
    manager = ArchiveNotes(path)
    created = manager.add_note(MEDIA_A, 2, "تعليق أول", author="reviewer")
    manager.update_note(created["note_id"], note_text="تعليق معدل", updated_by="editor")
    manager.delete_note(created["note_id"], actor="admin")
    manager.close()

    audit = AuditLog(path)
    try:
        events = audit.list_events(entity_type="media_note", entity_id=created["note_id"])
        assert [event["action"] for event in reversed(events)] == [
            "note_created",
            "note_updated",
            "note_deleted",
        ]
        assert {event["actor"] for event in events} == {
            "reviewer", "editor", "admin"
        }
    finally:
        audit.close()


@pytest.mark.parametrize("timestamp", [-1, float("nan"), float("inf"), True])
def test_add_note_rejects_invalid_timestamps(notes, timestamp):
    with pytest.raises((TypeError, ValueError)):
        notes.add_note(MEDIA_A, timestamp, "ملاحظة")


@pytest.mark.parametrize("media_id", ["", "not-a-hash", "A" * 64, None])
def test_add_note_rejects_invalid_media_ids(notes, media_id):
    with pytest.raises(ValueError):
        notes.add_note(media_id, 0, "ملاحظة")


@pytest.mark.parametrize("text", ["", "   ", None])
def test_add_note_rejects_empty_or_invalid_text(notes, text):
    with pytest.raises((TypeError, ValueError)):
        notes.add_note(MEDIA_A, 0, text)


def test_add_note_enforces_text_length(notes):
    with pytest.raises(ValueError, match="5000"):
        notes.add_note(MEDIA_A, 0, "x" * 5001)


def test_note_listing_and_updates_validate_arguments(notes):
    with pytest.raises(ValueError, match="Limit"):
        notes.list_notes(MEDIA_A, limit=0)
    with pytest.raises(ValueError, match="At least one"):
        created = notes.add_note(MEDIA_A, 0, "ملاحظة")
        notes.update_note(created["note_id"])
    with pytest.raises(KeyError):
        notes.update_note("f" * 32, note_text="غير موجود")


def test_note_table_has_timestamp_and_text_constraints(notes):
    with pytest.raises(sqlite3.IntegrityError):
        notes.connection.execute(
            """
            INSERT INTO archive_notes (
                note_id, media_id, timestamp_seconds, note_text, author,
                created_at, updated_at, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("c" * 32, MEDIA_A, -1, "bad", "editor", "now", "now", "editor"),
        )
