
import sqlite3
import pytest

from src.database.database_manager import DatabaseManager


def insert_segment(
    db,
    video_id="video_1",
    start=1.0,
    end=3.0,
    original_text="مرحبا",
    normalized_text="مرحبا",
):
    db.connection.execute(
        """
        INSERT INTO segments (
            video_id, start, end, original_text, normalized_text
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (video_id, start, end, original_text, normalized_text),
    )
    db.connection.commit()


def test_database_creation(tmp_path):
    db_path = tmp_path / "database" / "test.db"
    db = DatabaseManager(str(db_path))

    assert db_path.exists()

    tables = db.connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type IN ('table', 'view')
        """
    ).fetchall()

    table_names = [row["name"] for row in tables]

    assert "segments" in table_names
    assert "segments_fts" in table_names

    db.close()


def test_insert_segment(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))

    insert_segment(db)

    result = db.connection.execute(
        "SELECT * FROM segments"
    ).fetchone()

    assert result["video_id"] == "video_1"
    assert result["original_text"] == "مرحبا"

    db.close()


def test_fts_search_after_insert(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))

    insert_segment(db, normalized_text="مرحبا بالعالم")

    results = db.connection.execute(
        """
        SELECT rowid FROM segments_fts
        WHERE segments_fts MATCH ?
        """,
        ("مرحبا",),
    ).fetchall()

    assert len(results) == 1

    db.close()


def test_fts_updates_after_segment_update(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))

    insert_segment(db, normalized_text="النص القديم")

    db.connection.execute(
        "UPDATE segments SET normalized_text = ? WHERE id = 1",
        ("النص الجديد",),
    )
    db.connection.commit()

    old_results = db.connection.execute(
        "SELECT rowid FROM segments_fts WHERE segments_fts MATCH ?",
        ("القديم",),
    ).fetchall()

    new_results = db.connection.execute(
        "SELECT rowid FROM segments_fts WHERE segments_fts MATCH ?",
        ("الجديد",),
    ).fetchall()

    assert len(old_results) == 0
    assert len(new_results) == 1

    db.close()


def test_fts_updates_after_segment_delete(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))

    insert_segment(db, normalized_text="نص للحذف")

    db.connection.execute(
        "DELETE FROM segments WHERE id = 1"
    )
    db.connection.commit()

    results = db.connection.execute(
        "SELECT rowid FROM segments_fts WHERE segments_fts MATCH ?",
        ("للحذف",),
    ).fetchall()

    assert len(results) == 0

    db.close()


def test_invalid_insert_timestamps_are_rejected(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))

    with pytest.raises(sqlite3.IntegrityError):
        insert_segment(db, start=3, end=2)

    db.close()


def test_invalid_update_timestamps_are_rejected(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))

    insert_segment(db)

    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "UPDATE segments SET end = 0 WHERE id = 1"
        )

    db.close()


def test_database_persists_after_reopening(tmp_path):
    db_path = tmp_path / "test.db"

    db = DatabaseManager(str(db_path))
    insert_segment(db, original_text="بيانات محفوظة")
    db.close()

    reopened_db = DatabaseManager(str(db_path))

    result = reopened_db.connection.execute(
        "SELECT original_text FROM segments WHERE id = 1"
    ).fetchone()

    assert result["original_text"] == "بيانات محفوظة"

    reopened_db.close()
