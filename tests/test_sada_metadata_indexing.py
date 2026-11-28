from src.indexing.indexer import TranscriptIndexer


def test_indexer_persists_sada_speaker_and_dialect_metadata(tmp_path):
    indexer = TranscriptIndexer(str(tmp_path / "sada.db"))
    try:
        indexer.index_segments(
            "episode-1",
            [{
                "start": 1.0,
                "end": 2.5,
                "text": "مرحبا",
                "speaker": "speaker-01",
                "speaker_age": "Adult",
                "speaker_gender": "Female",
                "speaker_dialect": "Najdi",
                "environment": "Clean",
                "category": "Interview",
                "show_name": "Sample Show",
                "source_segment_id": "segment-0001",
                "segment_length": 1.5,
            }],
        )
        row = indexer.db.connection.execute(
            "SELECT speaker, speaker_age, speaker_gender, speaker_dialect, "
            "environment, category, show_name, source_segment_id, segment_length "
            "FROM segments WHERE video_id = ?",
            ("episode-1",),
        ).fetchone()
        assert tuple(row) == (
            "speaker-01", "Adult", "Female", "Najdi", "Clean",
            "Interview", "Sample Show", "segment-0001", 1.5,
        )
    finally:
        indexer.close()
