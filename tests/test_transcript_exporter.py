
import csv
import pytest

from src.transcription.transcript_exporter import TranscriptExporter


@pytest.fixture
def segments():
    return [
        {
            "start": 0.0,
            "end": 2.5,
            "text": "مرحبا بكم"
        },
        {
            "start": 2.5,
            "end": 5.0,
            "text": "هذا اختبار للتصدير"
        }
    ]


def test_export_csv_success(tmp_path, segments):
    output = tmp_path / "transcripts" / "result.csv"

    result = TranscriptExporter.export_csv(
        segments, str(output), "video_1"
    )

    assert result == output
    assert output.exists()


def test_export_csv_headers(tmp_path, segments):
    output = tmp_path / "result.csv"

    TranscriptExporter.export_csv(segments, str(output))

    with output.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        assert next(reader) == ["video_id", "start", "end", "text"]


def test_export_csv_preserves_arabic(tmp_path, segments):
    output = tmp_path / "result.csv"

    TranscriptExporter.export_csv(segments, str(output))

    with output.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert rows[0]["text"] == "مرحبا بكم"


def test_export_csv_includes_video_id(tmp_path, segments):
    output = tmp_path / "result.csv"

    TranscriptExporter.export_csv(
        segments, str(output), "video_123"
    )

    with output.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert all(row["video_id"] == "video_123" for row in rows)


def test_export_csv_all_segments(tmp_path, segments):
    output = tmp_path / "result.csv"

    TranscriptExporter.export_csv(segments, str(output))

    with output.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 2


def test_export_csv_creates_parent_directory(tmp_path, segments):
    output = tmp_path / "new_folder" / "result.csv"

    TranscriptExporter.export_csv(segments, str(output))

    assert output.exists()


def test_export_csv_empty_segments(tmp_path):
    output = tmp_path / "empty.csv"

    TranscriptExporter.export_csv([], str(output))

    assert output.exists()


def test_export_csv_rejects_invalid_segments(tmp_path):
    output = tmp_path / "invalid.csv"

    with pytest.raises(TypeError):
        TranscriptExporter.export_csv("invalid", str(output))


def test_export_csv_rejects_invalid_video_id(tmp_path, segments):
    output = tmp_path / "result.csv"

    with pytest.raises(TypeError):
        TranscriptExporter.export_csv(segments, str(output), 123)


def test_export_csv_preserves_timestamps(tmp_path, segments):
    output = tmp_path / "result.csv"

    TranscriptExporter.export_csv(segments, str(output))

    with output.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert float(rows[0]["start"]) == 0.0
    assert float(rows[0]["end"]) == 2.5
