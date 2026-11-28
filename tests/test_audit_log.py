import sqlite3

import pytest

from src.media.audit_log import AuditLog


def test_audit_log_persists_and_filters_events(tmp_path):
    path = tmp_path / "audit.db"
    log = AuditLog(path)
    created = log.record(
        "metadata_updated",
        "media",
        "media-1",
        {"before": {"tags": []}, "after": {"tags": ["news"]}},
        actor="editor@example.test",
    )
    log.close()

    reopened = AuditLog(path)
    events = reopened.list_events(entity_type="media", entity_id="media-1")
    assert len(events) == 1
    assert events[0]["event_id"] == created["event_id"]
    assert events[0]["actor"] == "editor@example.test"
    assert events[0]["details"]["after"]["tags"] == ["news"]
    assert reopened.list_events(actor="other") == []
    reopened.close()


@pytest.mark.parametrize("field", ["action", "entity_type", "entity_id", "actor"])
def test_audit_log_rejects_empty_required_fields(tmp_path, field):
    log = AuditLog(tmp_path / "audit.db")
    values = {
        "action": "changed",
        "entity_type": "media",
        "entity_id": "m1",
        "actor": "system",
    }
    values[field] = " "
    with pytest.raises(ValueError):
        log.record(**values)
    log.close()


def test_audit_log_rejects_non_json_details(tmp_path):
    log = AuditLog(tmp_path / "audit.db")
    with pytest.raises(ValueError, match="JSON"):
        log.record("changed", "media", "m1", {"bad": object()})
    log.close()


def test_audit_log_validates_limit_and_filters(tmp_path):
    log = AuditLog(tmp_path / "audit.db")
    with pytest.raises(ValueError, match="Limit"):
        log.list_events(limit=0)
    with pytest.raises(ValueError, match="filter"):
        log.list_events(actor=" ")
    log.close()



def test_audit_events_reject_update_and_delete_at_database_level(tmp_path):
    path = tmp_path / "immutable-audit.db"
    log = AuditLog(path)
    event = log.record(
        "metadata_updated",
        "media",
        "media-1",
        {"status": "transcribed"},
    )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        log.connection.execute(
            "UPDATE audit_events SET actor = 'tampered' WHERE event_id = ?",
            (event["event_id"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        log.connection.execute(
            "DELETE FROM audit_events WHERE event_id = ?",
            (event["event_id"],),
        )

    assert len(log.list_events(entity_id="media-1")) == 1
    log.close()


def test_audit_immutability_triggers_are_added_to_existing_databases(tmp_path):
    path = tmp_path / "legacy-audit.db"
    connection = sqlite3.connect(path)
    connection.execute("""
        CREATE TABLE audit_events (
            event_id TEXT PRIMARY KEY,
            occurred_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            details_json TEXT NOT NULL
        )
    """)
    connection.commit()
    connection.close()

    log = AuditLog(path)
    triggers = {
        row["name"]
        for row in log.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    }
    assert "audit_events_reject_update" in triggers
    assert "audit_events_reject_delete" in triggers
    log.record("new_event", "media", "media-2")
    log.close()
