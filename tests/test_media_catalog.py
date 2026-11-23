import json
from pathlib import Path

import pytest

from src.media.media_catalog import MediaCatalog


MEDIA_ID = "a" * 64


def test_register_and_retrieve_video_metadata(tmp_path):
    catalog = MediaCatalog(str(tmp_path / "database" / "media_catalog.json"))

    record = catalog.register_media(
        MEDIA_ID,
        "video",
        "interview.mp4",
        "data/videos/interview.mp4",
    )

    assert record["media_id"] == MEDIA_ID
    assert record["media_type"] == "video"
    assert record["source_name"] == "interview.mp4"
    assert record["status"] == "uploaded"
    assert catalog.get_by_id(MEDIA_ID) == record
    assert catalog.get_all() == [record]


def test_registering_existing_media_updates_metadata_and_preserves_date(
    tmp_path,
):
    catalog = MediaCatalog(str(tmp_path / "media_catalog.json"))

    first = catalog.register_media(
        MEDIA_ID,
        "audio",
        "original.mp3",
        "data/audio/originals/original.mp3",
    )
    updated = catalog.register_media(
        MEDIA_ID,
        "audio",
        "renamed.mp3",
        "data/audio/originals/renamed.mp3",
        status="processing",
    )

    assert updated["created_at"] == first["created_at"]
    assert updated["source_name"] == "renamed.mp3"
    assert updated["stored_path"].endswith("renamed.mp3")
    assert updated["status"] == "processing"
    assert len(catalog.get_all()) == 1


def test_update_status_records_and_clears_error(tmp_path):
    catalog = MediaCatalog(str(tmp_path / "media_catalog.json"))
    catalog.register_media(
        MEDIA_ID,
        "audio",
        "recording.wav",
        "data/audio/originals/recording.wav",
    )

    failed = catalog.update_status(MEDIA_ID, "failed", "FFmpeg failed")
    assert failed["status"] == "failed"
    assert failed["error"] == "FFmpeg failed"

    completed = catalog.update_status(MEDIA_ID, "transcribed")
    assert completed["status"] == "transcribed"
    assert "error" not in completed


@pytest.mark.parametrize(
    ("media_id", "media_type", "source_name", "stored_path", "status"),
    [
        ("not-a-hash", "audio", "file.mp3", "file.mp3", "uploaded"),
        (MEDIA_ID, "image", "file.png", "file.png", "uploaded"),
        (MEDIA_ID, "audio", "", "file.mp3", "uploaded"),
        (MEDIA_ID, "audio", "file.mp3", "", "uploaded"),
        (MEDIA_ID, "audio", "file.mp3", "file.mp3", "unknown"),
    ],
)
def test_register_rejects_invalid_metadata(
    tmp_path,
    media_id,
    media_type,
    source_name,
    stored_path,
    status,
):
    catalog = MediaCatalog(str(tmp_path / "media_catalog.json"))

    with pytest.raises(ValueError):
        catalog.register_media(
            media_id,
            media_type,
            source_name,
            stored_path,
            status,
        )


def test_update_missing_media_raises_key_error(tmp_path):
    catalog = MediaCatalog(str(tmp_path / "media_catalog.json"))

    with pytest.raises(KeyError):
        catalog.update_status(MEDIA_ID, "transcribed")


def test_corrupt_catalog_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "media_catalog.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")
    catalog = MediaCatalog(str(path))

    with pytest.raises(ValueError, match="JSON list"):
        catalog.get_all()

    assert path.read_text(encoding="utf-8") == '{"not": "a list"}'


@pytest.mark.parametrize("invalid_value", [None, [], {}])
def test_register_rejects_non_string_type_and_status_values(
    tmp_path,
    invalid_value,
):
    catalog = MediaCatalog(str(tmp_path / "media_catalog.json"))

    with pytest.raises(ValueError):
        catalog.register_media(
            MEDIA_ID,
            invalid_value,
            "file.mp3",
            "file.mp3",
        )

    with pytest.raises(ValueError):
        catalog.register_media(
            MEDIA_ID,
            "audio",
            "file.mp3",
            "file.mp3",
            status=invalid_value,
        )


def test_catalog_rejects_invalid_persisted_record_without_overwriting(tmp_path):
    path = tmp_path / "media_catalog.json"
    record = {
        "media_id": MEDIA_ID,
        "media_type": "audio",
        "source_name": "recording.mp3",
        "stored_path": "data/audio/recording.mp3",
        "status": "unknown",
        "created_at": "2026-11-21T10:00:00+00:00",
    }
    original = json.dumps([record])
    path.write_text(original, encoding="utf-8")
    catalog = MediaCatalog(str(path))

    with pytest.raises(ValueError, match="status"):
        catalog.get_all()

    assert path.read_text(encoding="utf-8") == original


def test_catalog_rejects_duplicate_media_ids(tmp_path):
    path = tmp_path / "media_catalog.json"
    record = {
        "media_id": MEDIA_ID,
        "media_type": "audio",
        "source_name": "recording.mp3",
        "stored_path": "data/audio/recording.mp3",
        "status": "uploaded",
        "created_at": "2026-11-21T10:00:00+00:00",
    }
    path.write_text(
        json.dumps([record, record]),
        encoding="utf-8",
    )
    catalog = MediaCatalog(str(path))

    with pytest.raises(ValueError, match="duplicate ID"):
        catalog.get_all()

def test_archive_metadata_is_additive_and_legacy_records_remain_readable(tmp_path):
    path = tmp_path / "media_catalog.json"
    path.write_text(
        json.dumps([{
            "media_id": MEDIA_ID,
            "media_type": "video",
            "source_name": "legacy.mp4",
            "stored_path": "data/videos/legacy.mp4",
            "status": "transcribed",
            "created_at": "2026-11-21T10:00:00+00:00",
        }]),
        encoding="utf-8",
    )
    catalog = MediaCatalog(str(path))

    updated = catalog.update_archive_metadata(
        MEDIA_ID,
        collection="News Archive",
        tags=["Politics", "Interview"],
    )

    assert updated["collection"] == "News Archive"
    assert updated["tags"] == ["Politics", "Interview"]
    assert catalog.get_by_id(MEDIA_ID)["status"] == "transcribed"
    assert catalog.get_collections() == ["News Archive"]
    assert catalog.get_all_tags() == ["Interview", "Politics"]


def test_archive_metadata_normalizes_duplicate_tags_and_supports_removal(tmp_path):
    catalog = MediaCatalog(str(tmp_path / "media_catalog.json"))
    catalog.register_media(
        MEDIA_ID, "audio", "recording.mp3", "data/audio/recording.mp3"
    )

    updated = catalog.update_archive_metadata(
        MEDIA_ID,
        collection="  Interviews  ",
        tags=["News", " news ", "Arabic"],
    )
    assert updated["tags"] == ["News", "Arabic"]

    cleared = catalog.update_archive_metadata(MEDIA_ID)
    assert "collection" not in cleared
    assert "tags" not in cleared
    assert catalog.get_collections() == []
    assert catalog.get_all_tags() == []


def test_filter_media_matches_collection_case_insensitively_and_all_tags(tmp_path):
    catalog = MediaCatalog(str(tmp_path / "media_catalog.json"))
    catalog.register_media(
        MEDIA_ID, "video", "one.mp4", "data/videos/one.mp4"
    )
    second_id = "b" * 64
    catalog.register_media(
        second_id, "audio", "two.mp3", "data/audio/two.mp3"
    )
    catalog.update_archive_metadata(
        MEDIA_ID, collection="News", tags=["Arabic", "Interview"]
    )
    catalog.update_archive_metadata(
        second_id, collection="Sports", tags=["Arabic"]
    )

    result = catalog.filter_media(
        collection="news",
        tags=["arabic", "INTERVIEW"],
    )

    assert [item["media_id"] for item in result] == [MEDIA_ID]
    assert [item["media_id"] for item in catalog.filter_media(tags=["Arabic"])] == [
        MEDIA_ID, second_id
    ]


def test_archive_metadata_rejects_invalid_values_without_mutating_catalog(tmp_path):
    catalog = MediaCatalog(str(tmp_path / "media_catalog.json"))
    catalog.register_media(
        MEDIA_ID, "audio", "recording.mp3", "data/audio/recording.mp3"
    )
    original = catalog.get_by_id(MEDIA_ID)

    with pytest.raises(ValueError):
        catalog.update_archive_metadata(MEDIA_ID, tags=["valid", " "])
    with pytest.raises(TypeError):
        catalog.update_archive_metadata(MEDIA_ID, tags="not-a-list")
    with pytest.raises(KeyError):
        catalog.update_archive_metadata("c" * 64, collection="Missing")

    assert catalog.get_by_id(MEDIA_ID) == original


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("collection", " ", "collection"),
        ("tags", ["valid", ""], "tags"),
        ("tags", "not-a-list", "tags"),
        ("tags", ["Duplicate", "duplicate"], "tags"),
    ],
)
def test_catalog_rejects_invalid_persisted_collection_and_tags(
    tmp_path, field, value, message
):
    path = tmp_path / "media_catalog.json"
    record = {
        "media_id": MEDIA_ID,
        "media_type": "audio",
        "source_name": "recording.mp3",
        "stored_path": "data/audio/recording.mp3",
        "status": "uploaded",
        "created_at": "2026-11-21T10:00:00+00:00",
        field: value,
    }
    original = json.dumps([record])
    path.write_text(original, encoding="utf-8")
    catalog = MediaCatalog(str(path))

    with pytest.raises(ValueError, match=message):
        catalog.get_all()
    assert path.read_text(encoding="utf-8") == original


def test_archive_metadata_changes_are_audited(tmp_path):
    from src.media.audit_log import AuditLog

    catalog = MediaCatalog(
        tmp_path / "catalog.json",
        audit_database_path=tmp_path / "audit.db",
    )
    media_id = "a" * 64
    catalog.register_media(media_id, "video", "interview.mp4", "/archive/interview.mp4")
    catalog.update_archive_metadata(
        media_id, collection="News", tags=["Arabic", "Politics"], actor="editor"
    )

    audit = AuditLog(tmp_path / "audit.db")
    events = audit.list_events(entity_type="media", entity_id=media_id)
    metadata_event = next(
        event for event in events if event["action"] == "media_metadata_updated"
    )
    assert metadata_event["actor"] == "editor"
    assert metadata_event["details"]["before"].get("collection") is None
    assert metadata_event["details"]["after"]["collection"] == "News"
    assert metadata_event["details"]["after"]["tags"] == ["Arabic", "Politics"]
    audit.close()


def test_filter_media_supports_type_source_and_added_date_range(tmp_path):
    catalog = MediaCatalog(
        tmp_path / "catalog.json",
        audit_database_path=tmp_path / "audit.db",
    )
    video_id = "d" * 64
    audio_id = "e" * 64
    catalog.register_media(video_id, "video", "Daily_News.mp4", "/archive/news.mp4")
    catalog.register_media(audio_id, "audio", "Interview.wav", "/archive/interview.wav")
    records = catalog.get_all()
    records[0]["created_at"] = "2026-11-20T10:00:00+00:00"
    records[1]["created_at"] = "2026-11-22T10:00:00+00:00"
    catalog._save(records)

    result = catalog.filter_media(
        media_type="video",
        source_contains="daily",
        start_date="2026-11-19",
        end_date="2026-11-21",
    )
    assert [item["media_id"] for item in result] == [video_id]


def test_filter_media_rejects_invalid_type_and_date_range(tmp_path):
    catalog = MediaCatalog(
        tmp_path / "catalog.json",
        audit_database_path=tmp_path / "audit.db",
    )
    with pytest.raises(ValueError, match="Media type"):
        catalog.filter_media(media_type="image")
    with pytest.raises(ValueError, match="after end"):
        catalog.filter_media(
            start_date="2026-11-22",
            end_date="2026-11-20",
        )
