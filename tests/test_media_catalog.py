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
