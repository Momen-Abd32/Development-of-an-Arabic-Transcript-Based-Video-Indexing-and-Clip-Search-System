from pathlib import Path

from src.media.archive_metrics import ArchiveMetrics
from src.media.media_catalog import MediaCatalog
from src.media.processing_queue import ProcessingQueue


def test_archive_metrics_summarize_catalog_storage_queue_and_health(
    tmp_path, monkeypatch
):
    root = tmp_path / "archive"
    root.mkdir()
    video = root / "video.mp4"
    audio = root / "audio.mp3"
    video.write_bytes(b"video-bytes")
    audio.write_bytes(b"audio")

    catalog_path = tmp_path / "media_catalog.json"
    catalog = MediaCatalog(str(catalog_path))
    catalog.register_media("a" * 64, "video", "video.mp4", str(video), "transcribed")
    catalog.register_media("b" * 64, "audio", "audio.mp3", str(audio), "failed")

    queue_path = tmp_path / "queue.db"
    queue = ProcessingQueue(queue_path)
    queued_job = queue.enqueue("batch_import", {"input_directory": str(root)})
    cancelled_job = queue.enqueue("batch_import", {"input_directory": str(root)})
    queue.cancel(cancelled_job["job_id"])
    queue.close()

    database_path = tmp_path / "videos.db"
    import sqlite3
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE health_check (id INTEGER)")
        connection.commit()

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "one.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "src.media.archive_metrics.shutil.which",
        lambda name: "/usr/bin/ffmpeg",
    )
    metrics = ArchiveMetrics(
        catalog_path=catalog_path,
        queue_path=queue_path,
        database_path=database_path,
        transcript_dir=transcript_dir,
    )
    result = metrics.collect()

    assert result["media_total"] == 2
    assert result["video_total"] == 1
    assert result["audio_total"] == 1
    assert result["status_counts"] == {"transcribed": 1, "failed": 1}
    assert result["storage_bytes"] == len(b"video-bytes") + len(b"audio")
    assert result["missing_files"] == 0
    assert result["transcript_total"] == 1
    assert result["queue_counts"] == {"queued": 1, "cancelled": 1}
    assert result["database_health"] == "ok"
    assert result["ffmpeg_available"] is True
    assert "faster_whisper_available" in result
    assert "semantic_search_available" in result
    assert "diarization_available" in result
    metrics.close()


def test_archive_metrics_reports_missing_files_and_uninitialized_database(tmp_path):
    catalog_path = tmp_path / "media_catalog.json"
    catalog = MediaCatalog(str(catalog_path))
    catalog.register_media(
        "c" * 64,
        "video",
        "missing.mp4",
        str(tmp_path / "missing.mp4"),
    )

    metrics = ArchiveMetrics(
        catalog_path=catalog_path,
        queue_path=tmp_path / "queue.db",
        database_path=tmp_path / "missing.db",
        transcript_dir=tmp_path / "no-transcripts",
    )
    result = metrics.collect()

    assert result["missing_files"] == 1
    assert result["storage_bytes"] == 0
    assert result["database_health"] == "not_initialized"
    metrics.close()
