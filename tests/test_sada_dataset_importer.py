import csv

from src.media.sada_dataset_importer import (
    SadaDatasetImporter,
    _first_episodes,
    _segments_for_episodes,
)


def _write_split(root):
    (root / "batch_1").mkdir(parents=True)
    rows = [
        {
            "FileName": "batch_1/episode_a.wav",
            "SegmentStart": "0.25",
            "SegmentEnd": "1.5",
            "GroundTruthText": "مرحبا بالعالم",
            "ProcessedText": "مرحبا بالعالم",
            "Speaker": "Speaker 1",
        },
        {
            "FileName": "batch_1/episode_a.wav",
            "SegmentStart": "1.6",
            "SegmentEnd": "2.8",
            "GroundTruthText": "",
            "ProcessedText": "هذا اختبار",
            "Speaker": "Speaker 2",
        },
        {
            "FileName": "batch_1/episode_b.wav",
            "SegmentStart": "0",
            "SegmentEnd": "2",
            "GroundTruthText": "مقطع آخر",
            "ProcessedText": "مقطع آخر",
            "Speaker": "",
        },
    ]
    with (root / "train.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    (root / "batch_1" / "episode_a.wav").write_bytes(b"audio-a")
    (root / "batch_1" / "episode_b.wav").write_bytes(b"audio-b")


def test_selects_unique_episode_names_in_csv_order(tmp_path):
    _write_split(tmp_path)
    assert _first_episodes(tmp_path / "train.csv", 1) == ["batch_1/episode_a.wav"]


def test_maps_sada_annotations_to_timestamped_segments(tmp_path):
    _write_split(tmp_path)
    grouped = _segments_for_episodes(
        tmp_path / "train.csv", {"batch_1/episode_a.wav"}
    )
    assert grouped["batch_1/episode_a.wav"] == [
        {"start": 0.25, "end": 1.5, "text": "مرحبا بالعالم", "speaker": "Speaker 1"},
        {"start": 1.6, "end": 2.8, "text": "هذا اختبار", "speaker": "Speaker 2"},
    ]


def test_imports_audio_and_supplied_transcript_without_whisper(tmp_path):
    _write_split(tmp_path)
    importer = SadaDatasetImporter(
        dataset_dir=str(tmp_path),
        max_episodes=1,
        audio_source_dir=str(tmp_path / "archive"),
        transcript_dir=str(tmp_path / "transcripts"),
        database_path=str(tmp_path / "index.db"),
        catalog_path=str(tmp_path / "catalog.json"),
    )
    result = importer.import_dataset()
    assert result[0]["status"] == "imported"
    assert result[0]["segments"] == 2
    assert (tmp_path / "transcripts" / f"{result[0]['media_id']}.json").is_file()


def test_dry_run_does_not_copy_or_index(tmp_path):
    _write_split(tmp_path)
    importer = SadaDatasetImporter(
        dataset_dir=str(tmp_path),
        max_episodes=1,
        audio_source_dir=str(tmp_path / "archive"),
        transcript_dir=str(tmp_path / "transcripts"),
        database_path=str(tmp_path / "index.db"),
        catalog_path=str(tmp_path / "catalog.json"),
    )
    result = importer.import_dataset(dry_run=True)
    assert result[0]["status"] == "ready"
    assert not (tmp_path / "archive").exists()


def test_reports_missing_audio_without_transcribing(tmp_path):
    (tmp_path / "train.csv").write_text(
        "FileName,SegmentStart,SegmentEnd,GroundTruthText\nbatch_1/missing.wav,0,1,مرحبا\n",
        encoding="utf-8",
    )
    importer = SadaDatasetImporter(
        dataset_dir=str(tmp_path),
        max_episodes=1,
        audio_source_dir=str(tmp_path / "archive"),
        transcript_dir=str(tmp_path / "transcripts"),
        database_path=str(tmp_path / "index.db"),
        catalog_path=str(tmp_path / "catalog.json"),
    )
    result = importer.import_dataset()
    assert result[0]["status"] == "missing_audio"
