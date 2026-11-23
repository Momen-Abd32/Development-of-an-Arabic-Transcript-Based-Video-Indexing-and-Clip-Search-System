import json
import sqlite3
from pathlib import Path

import pytest

from src.search.keyframe_search import KeyframeSearchIndex


class FakeVisualProvider:
    model_name = "fake-clip-v1"

    def embed_text(self, text):
        return [1.0, 0.0] if "سيارة" in text else [0.0, 1.0]

    def embed_images(self, image_paths):
        return [[1.0, 0.0] if "car" in path.name else [0.0, 1.0] for path in image_paths]


@pytest.fixture
def visual_index(tmp_path):
    index = KeyframeSearchIndex(tmp_path / "visual.db")
    yield index
    index.close()


def test_replaces_keyframe_metadata_and_keeps_real_timestamps(visual_index, tmp_path):
    frames = []
    for name in ("frame-1.jpg", "frame-2.jpg", "frame-3.jpg"):
        path = tmp_path / name
        path.write_bytes(b"image")
        frames.append(path)

    assert visual_index.replace_media_keyframes("media-a", frames, 12.5) == 3
    rows = visual_index.connection.execute(
        "SELECT frame_index, timestamp_seconds, image_path FROM keyframes ORDER BY frame_index"
    ).fetchall()
    assert [row["timestamp_seconds"] for row in rows] == [0.0, 12.5, 25.0]
    assert Path(rows[0]["image_path"]).is_absolute()

    assert visual_index.replace_media_keyframes("media-a", frames[:1], 10) == 1
    assert visual_index.connection.execute(
        "SELECT COUNT(*) FROM keyframes WHERE media_id = 'media-a'"
    ).fetchone()[0] == 1


def test_failed_keyframe_metadata_replacement_rolls_back(visual_index, tmp_path):
    good = tmp_path / "good.jpg"
    good.write_bytes(b"image")
    visual_index.replace_media_keyframes("media-a", [good])
    with pytest.raises(FileNotFoundError):
        visual_index.replace_media_keyframes("media-a", [tmp_path / "missing.jpg"])
    row = visual_index.connection.execute(
        "SELECT image_path FROM keyframes WHERE media_id = 'media-a'"
    ).fetchone()
    assert row["image_path"] == str(good.resolve())


def test_indexes_keyframes_and_searches_by_text_and_reference_image(visual_index, tmp_path):
    car = tmp_path / "car-frame.jpg"
    sea = tmp_path / "sea-frame.jpg"
    car.write_bytes(b"car")
    sea.write_bytes(b"sea")
    visual_index.replace_media_keyframes("media-a", [car, sea])
    provider = FakeVisualProvider()
    assert visual_index.index_media("media-a", provider, batch_size=1) == 2

    text_results = visual_index.search_text("سيارة حمراء", provider)
    assert text_results[0]["image_path"] == str(car.resolve())
    assert text_results[0]["timestamp_seconds"] == 0

    image_results = visual_index.search_image(car, provider)
    assert image_results[0]["media_id"] == "media-a"
    assert image_results[0]["visual_score"] == 1.0


def test_visual_search_filters_media_and_empty_filter(visual_index, tmp_path):
    frame = tmp_path / "car-frame.jpg"
    frame.write_bytes(b"car")
    visual_index.replace_media_keyframes("media-a", [frame])
    visual_index.replace_media_keyframes("media-b", [frame])
    provider = FakeVisualProvider()
    visual_index.index_media("media-a", provider)
    visual_index.index_media("media-b", provider)

    assert visual_index.search_text("سيارة", provider, media_ids=["media-b"])[0]["media_id"] == "media-b"
    assert visual_index.search_text("سيارة", provider, media_ids=[]) == []


def test_visual_index_rejects_invalid_vectors_and_limits(visual_index, tmp_path):
    class InvalidProvider(FakeVisualProvider):
        def embed_images(self, image_paths):
            return [[float("nan"), 0.0] for _ in image_paths]

    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    visual_index.replace_media_keyframes("media-a", [frame])
    with pytest.raises(ValueError, match="finite"):
        visual_index.index_media("media-a", InvalidProvider())
    with pytest.raises(ValueError, match="positive integer"):
        visual_index.search_text("سيارة", FakeVisualProvider(), limit=True)


def test_visual_index_preserves_previous_embeddings_when_reindex_fails(visual_index, tmp_path):
    frame = tmp_path / "car-frame.jpg"
    frame.write_bytes(b"car")
    visual_index.replace_media_keyframes("media-a", [frame])
    provider = FakeVisualProvider()
    visual_index.index_media("media-a", provider)

    class FailingProvider(FakeVisualProvider):
        def embed_images(self, image_paths):
            raise RuntimeError("model failed")

    with pytest.raises(RuntimeError, match="model failed"):
        visual_index.index_media("media-a", FailingProvider())

    results = visual_index.search_text("سيارة", provider)
    assert len(results) == 1


def test_persists_explicit_ffmpeg_presentation_timestamps(visual_index, tmp_path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    assert visual_index.replace_media_keyframes(
        "media-ts",
        [(first, 0.125), (second, 7.875)],
    ) == 2
    rows = visual_index.get_media_keyframes("media-ts")
    assert [row["timestamp_seconds"] for row in rows] == [0.125, 7.875]


def test_rejects_non_monotonic_explicit_timestamps(visual_index, tmp_path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    with pytest.raises(ValueError, match="increasing"):
        visual_index.replace_media_keyframes(
            "media-ts",
            [(first, 5.0), (second, 4.0)],
        )


def test_unchanged_keyframe_metadata_keeps_existing_embeddings(visual_index, tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    provider = FakeVisualProvider()
    visual_index.replace_media_keyframes("media-a", [frame], interval_seconds=15)
    visual_index.index_media("media-a", provider)

    assert visual_index.replace_media_keyframes(
        "media-a", [frame], interval_seconds=15
    ) == 1
    results = visual_index.search_text("سيارة", provider)
    assert len(results) == 1


def test_keyframe_embedding_rows_cascade_when_frame_is_deleted(visual_index, tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    visual_index.replace_media_keyframes("media-a", [frame])
    visual_index.index_media("media-a", FakeVisualProvider())
    visual_index.connection.execute(
        "DELETE FROM keyframes WHERE media_id = ?", ("media-a",)
    )
    visual_index.connection.commit()
    assert visual_index.connection.execute(
        "SELECT COUNT(*) FROM keyframe_embeddings"
    ).fetchone()[0] == 0


def test_changed_image_bytes_invalidate_old_visual_embeddings(visual_index, tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"original-frame")
    provider = FakeVisualProvider()
    visual_index.replace_media_keyframes("media-a", [frame])
    visual_index.index_media("media-a", provider)

    frame.write_bytes(b"changed-frame")
    visual_index.replace_media_keyframes("media-a", [frame])

    assert visual_index.connection.execute(
        "SELECT COUNT(*) FROM keyframe_embeddings"
    ).fetchone()[0] == 0
    assert visual_index.search_text("سيارة", provider) == []


def test_migrates_legacy_keyframe_table_with_image_hash_column(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE keyframes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id TEXT NOT NULL,
            frame_index INTEGER NOT NULL,
            timestamp_seconds REAL NOT NULL,
            image_path TEXT NOT NULL,
            UNIQUE(media_id, frame_index)
        )
        """
    )
    connection.commit()
    connection.close()

    index = KeyframeSearchIndex(database)
    try:
        columns = {
            row["name"]
            for row in index.connection.execute("PRAGMA table_info(keyframes)")
        }
        assert "image_sha256" in columns
    finally:
        index.close()
