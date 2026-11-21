import json
from pathlib import Path

from src.media.batch_processor import MediaBatchProcessor


class FakeIndexer:
    indexed = []

    def __init__(self, database_path):
        self.database_path = database_path

    def index_segments(self, media_id, segments):
        self.indexed.append((media_id, segments))

    def close(self):
        pass


def test_batch_processor_handles_audio_and_video(tmp_path, monkeypatch):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    video = input_dir / "interview.mp4"
    audio = input_dir / "recording.mp3"
    video.write_bytes(b"video content")
    audio.write_bytes(b"audio content")

    def fake_prepare(source, output):
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"normalized audio")
        return output_path

    class FakeEngine:
        def __init__(self, **kwargs):
            self.options = kwargs

        def transcribe(self, audio_path):
            return [{"start": 0.0, "end": 1.5, "text": "نص عربي"}]

    FakeIndexer.indexed = []
    monkeypatch.setattr(
        "src.media.batch_processor.AudioExtractor.prepare",
        fake_prepare,
    )
    monkeypatch.setattr(
        "src.media.batch_processor.FasterWhisperEngine",
        FakeEngine,
    )
    monkeypatch.setattr(
        "src.media.batch_processor.TranscriptIndexer",
        FakeIndexer,
    )

    processor = MediaBatchProcessor(
        video_dir=str(tmp_path / "stored_videos"),
        audio_source_dir=str(tmp_path / "stored_audio"),
        audio_dir=str(tmp_path / "normalized_audio"),
        transcript_dir=str(tmp_path / "transcripts"),
        database_path=str(tmp_path / "database.db"),
        catalog_path=str(tmp_path / "media_catalog.json"),
    )
    results = processor.process_directory(str(input_dir))

    assert [item["status"] for item in results] == ["processed", "processed"]
    assert {item["media_type"] for item in results} == {"audio", "video"}
    assert all(item["segments"] == 1 for item in results)
    assert len(FakeIndexer.indexed) == 2
    assert len(list((tmp_path / "transcripts").glob("*.json"))) == 2
    catalog = json.loads(
        (tmp_path / "media_catalog.json").read_text(encoding="utf-8")
    )
    assert len(catalog) == 2
    assert all(item["status"] == "transcribed" for item in catalog)


def test_batch_processor_skips_duplicate_content_in_same_batch(
    tmp_path,
    monkeypatch,
):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    first = input_dir / "first.mp3"
    second = input_dir / "second.wav"
    first.write_bytes(b"same media bytes")
    second.write_bytes(b"same media bytes")

    def fake_prepare(source, output):
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"normalized audio")
        return output_path

    class FakeEngine:
        def __init__(self, **kwargs):
            pass

        def transcribe(self, audio_path):
            return [{"start": 0.0, "end": 1.0, "text": "نص"}]

    FakeIndexer.indexed = []
    monkeypatch.setattr(
        "src.media.batch_processor.AudioExtractor.prepare",
        fake_prepare,
    )
    monkeypatch.setattr(
        "src.media.batch_processor.FasterWhisperEngine",
        FakeEngine,
    )
    monkeypatch.setattr(
        "src.media.batch_processor.TranscriptIndexer",
        FakeIndexer,
    )

    processor = MediaBatchProcessor(
        video_dir=str(tmp_path / "videos"),
        audio_source_dir=str(tmp_path / "audio_sources"),
        audio_dir=str(tmp_path / "audio"),
        transcript_dir=str(tmp_path / "transcripts"),
        database_path=str(tmp_path / "database.db"),
        catalog_path=str(tmp_path / "media_catalog.json"),
    )
    results = processor.process_directory(str(input_dir))

    assert [item["status"] for item in results] == [
        "processed",
        "duplicate_in_batch",
    ]
    assert len(FakeIndexer.indexed) == 1
    catalog = json.loads(
        (tmp_path / "media_catalog.json").read_text(encoding="utf-8")
    )
    assert catalog[0]["status"] == "transcribed"


def test_batch_processor_reuses_existing_transcript(tmp_path, monkeypatch):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    audio = input_dir / "recording.wav"
    audio.write_bytes(b"audio content")

    import hashlib
    media_id = hashlib.sha256(b"audio content").hexdigest()
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    transcript_path = transcript_dir / f"{media_id}.json"
    transcript_path.write_text(
        '{"segments":[{"start":0.0,"end":1.0,"text":"مرحبا"}],'
        '"total_segments":1}',
        encoding="utf-8",
    )

    FakeIndexer.indexed = []
    monkeypatch.setattr(
        "src.media.batch_processor.TranscriptIndexer",
        FakeIndexer,
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Existing transcript should be reused.")

    monkeypatch.setattr(
        "src.media.batch_processor.FasterWhisperEngine",
        fail_if_called,
    )
    monkeypatch.setattr(
        "src.media.batch_processor.AudioExtractor.prepare",
        fail_if_called,
    )

    processor = MediaBatchProcessor(
        video_dir=str(tmp_path / "videos"),
        audio_source_dir=str(tmp_path / "audio_sources"),
        audio_dir=str(tmp_path / "audio"),
        transcript_dir=str(transcript_dir),
        database_path=str(tmp_path / "database.db"),
        catalog_path=str(tmp_path / "media_catalog.json"),
    )
    results = processor.process_directory(str(input_dir))

    assert results[0]["status"] == "already_transcribed"
    assert results[0]["segments"] == 1
    assert len(FakeIndexer.indexed) == 1


def test_batch_processor_validates_input_directory(tmp_path):
    processor = MediaBatchProcessor()

    missing = tmp_path / "missing"
    try:
        processor.process_directory(str(missing))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Missing directory should raise FileNotFoundError.")

    file_path = tmp_path / "not_a_directory.txt"
    file_path.write_text("x", encoding="utf-8")
    try:
        processor.process_directory(str(file_path))
    except ValueError:
        pass
    else:
        raise AssertionError("A file path should raise ValueError.")



def test_batch_processor_retries_duplicate_after_first_failure(
    tmp_path,
    monkeypatch,
):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    (input_dir / "first.mp3").write_bytes(b"same bytes")
    (input_dir / "second.wav").write_bytes(b"same bytes")
    prepare_calls = []

    def flaky_prepare(source, output):
        prepare_calls.append(source)
        if len(prepare_calls) == 1:
            raise RuntimeError("temporary conversion failure")
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"normalized audio")
        return output_path

    class FakeEngine:
        def __init__(self, **kwargs):
            pass

        def transcribe(self, audio_path):
            return [{"start": 0.0, "end": 1.0, "text": "نص"}]

    FakeIndexer.indexed = []
    monkeypatch.setattr(
        "src.media.batch_processor.AudioExtractor.prepare",
        flaky_prepare,
    )
    monkeypatch.setattr(
        "src.media.batch_processor.FasterWhisperEngine",
        FakeEngine,
    )
    monkeypatch.setattr(
        "src.media.batch_processor.TranscriptIndexer",
        FakeIndexer,
    )

    processor = MediaBatchProcessor(
        video_dir=str(tmp_path / "videos"),
        audio_source_dir=str(tmp_path / "audio_sources"),
        audio_dir=str(tmp_path / "audio"),
        transcript_dir=str(tmp_path / "transcripts"),
        database_path=str(tmp_path / "database.db"),
        catalog_path=str(tmp_path / "media_catalog.json"),
    )
    results = processor.process_directory(str(input_dir))

    assert [item["status"] for item in results] == ["failed", "processed"]
    assert len(prepare_calls) == 2


def test_store_source_replaces_corrupt_existing_archive_copy(tmp_path):
    import hashlib

    source = tmp_path / "incoming.mp3"
    source.write_bytes(b"correct media bytes")
    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    destination = tmp_path / "archive" / f"{expected_hash}.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"corrupt partial copy")

    stored = MediaBatchProcessor._store_source(
        source,
        destination,
        expected_hash,
    )

    assert stored == destination
    assert destination.read_bytes() == source.read_bytes()


def test_store_source_rejects_changed_file_during_copy(tmp_path, monkeypatch):
    import hashlib

    source = tmp_path / "incoming.mp3"
    source.write_bytes(b"original media bytes")
    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / "archive" / f"{expected_hash}.mp3"

    def copy_changed_content(source_path, destination_path):
        Path(destination_path).write_bytes(b"changed while copying")

    monkeypatch.setattr(
        "src.media.batch_processor.shutil.copy2",
        copy_changed_content,
    )

    import pytest

    with pytest.raises(RuntimeError, match="changed"):
        MediaBatchProcessor._store_source(
            source,
            destination,
            expected_hash,
        )

    assert not destination.exists()
    assert not list(destination.parent.glob(".*.tmp"))
