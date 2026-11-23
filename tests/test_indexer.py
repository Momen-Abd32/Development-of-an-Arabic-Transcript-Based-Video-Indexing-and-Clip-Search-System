
import sqlite3
import pytest

from src.indexing.indexer import TranscriptIndexer


def sample_segments():
    return [
        {
            "start": 0.5,
            "end": 2.5,
            "text": "إِنَّ البرمجة جميلة",
        },
        {
            "start": 2.5,
            "end": 4.0,
            "text": "مرحبا بالعالم",
        },
    ]


def test_index_segments(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "test.db"))

    count = indexer.index_segments("video_1", sample_segments())

    assert count == 2

    rows = indexer.db.connection.execute(
        "SELECT * FROM segments WHERE video_id = ?",
        ("video_1",),
    ).fetchall()

    assert len(rows) == 2

    indexer.close()


def test_indexer_normalizes_arabic_text(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "test.db"))

    indexer.index_segments("video_1", sample_segments())

    row = indexer.db.connection.execute(
        "SELECT normalized_text FROM segments WHERE id = 1"
    ).fetchone()

    assert row["normalized_text"] == "ان البرمجة جميلة"

    indexer.close()


def test_reindex_does_not_duplicate_segments(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "test.db"))

    first_count = indexer.index_segments(
        "video_1", sample_segments()
    )

    second_count = indexer.index_segments(
        "video_1", sample_segments()
    )

    total = indexer.db.connection.execute(
        "SELECT COUNT(*) FROM segments WHERE video_id = ?",
        ("video_1",),
    ).fetchone()[0]

    assert first_count == 2
    assert second_count == 2
    assert total == 2

    indexer.close()


def test_reindex_replaces_old_segments(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "test.db"))

    indexer.index_segments("video_1", sample_segments())

    new_segments = [
        {
            "start": 10.0,
            "end": 12.0,
            "text": "النص الجديد",
        }
    ]

    count = indexer.index_segments("video_1", new_segments)

    rows = indexer.db.connection.execute(
        "SELECT * FROM segments WHERE video_id = ?",
        ("video_1",),
    ).fetchall()

    assert count == 1
    assert len(rows) == 1
    assert rows[0]["original_text"] == "النص الجديد"

    indexer.close()


def test_indexing_one_video_does_not_affect_another(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "test.db"))

    indexer.index_segments("video_1", sample_segments())
    indexer.index_segments("video_2", sample_segments())

    indexer.index_segments(
        "video_1",
        [{"start": 1, "end": 2, "text": "مقطع جديد"}],
    )

    video_2_count = indexer.db.connection.execute(
        "SELECT COUNT(*) FROM segments WHERE video_id = ?",
        ("video_2",),
    ).fetchone()[0]

    assert video_2_count == 2

    indexer.close()


def test_reindex_invalidates_old_semantic_embeddings(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "test.db"))
    indexer.index_segments("video_1", sample_segments())

    indexer.db.connection.execute(
        """
        INSERT INTO segment_embeddings
            (segment_id, video_id, model_name, embedding_json)
        VALUES (1, 'video_1', 'test-model', '[1.0, 0.0]')
        """
    )
    indexer.db.connection.commit()

    indexer.index_segments(
        "video_1",
        [{"start": 5, "end": 6, "text": "نص معدل"}],
    )

    remaining = indexer.db.connection.execute(
        "SELECT COUNT(*) FROM segment_embeddings WHERE video_id = ?",
        ("video_1",),
    ).fetchone()[0]

    assert remaining == 0
    indexer.close()


def test_empty_video_id_is_rejected(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "test.db"))

    with pytest.raises(ValueError):
        indexer.index_segments("", sample_segments())

    indexer.close()


def test_failed_indexing_rolls_back_previous_data(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "test.db"))

    indexer.index_segments("video_1", sample_segments())

    invalid_segments = [
        {
            "start": 1,
            "end": 2,
            "text": "مقطع صحيح",
        },
        {
            "start": 3,
            "end": 2,
            "text": "مقطع بتوقيت خاطئ",
        },
    ]

    with pytest.raises(sqlite3.IntegrityError):
        indexer.index_segments("video_1", invalid_segments)

    rows = indexer.db.connection.execute(
        "SELECT * FROM segments WHERE video_id = ?",
        ("video_1",),
    ).fetchall()

    assert len(rows) == 2
    assert rows[0]["original_text"] == "إِنَّ البرمجة جميلة"

    indexer.close()


def test_empty_segments_remove_previous_index(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "test.db"))

    indexer.index_segments("video_1", sample_segments())

    count = indexer.index_segments("video_1", [])

    remaining = indexer.db.connection.execute(
        "SELECT COUNT(*) FROM segments WHERE video_id = ?",
        ("video_1",),
    ).fetchone()[0]

    assert count == 0
    assert remaining == 0

    indexer.close()
