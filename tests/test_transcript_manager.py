
import json
import pytest

from src.transcription.transcript_manager import TranscriptManager


def sample_segments():
    return [
        {
            "start": 0.5,
            "end": 2.5,
            "text": "مرحبا كيف حالك",
        },
        {
            "start": 2.5,
            "end": 4.0,
            "text": "أنا بخير",
        },
    ]


def test_save_transcript(tmp_path):
    output = tmp_path / "transcripts" / "sample.json"

    result = TranscriptManager.save(sample_segments(), str(output))

    assert result == output
    assert output.exists()


def test_save_preserves_arabic_text(tmp_path):
    output = tmp_path / "sample.json"

    TranscriptManager.save(sample_segments(), str(output))

    content = output.read_text(encoding="utf-8")
    assert "مرحبا كيف حالك" in content


def test_save_includes_total_segments(tmp_path):
    output = tmp_path / "sample.json"

    TranscriptManager.save(sample_segments(), str(output))

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["total_segments"] == 2


def test_load_transcript(tmp_path):
    output = tmp_path / "sample.json"
    TranscriptManager.save(sample_segments(), str(output))

    result = TranscriptManager.load(str(output))

    assert result == sample_segments()


def test_load_missing_file_raises_error(tmp_path):
    missing = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError):
        TranscriptManager.load(str(missing))


def test_load_invalid_json_structure(tmp_path):
    output = tmp_path / "invalid.json"
    output.write_text('{"wrong_key": []}', encoding="utf-8")

    with pytest.raises(ValueError):
        TranscriptManager.load(str(output))


def test_save_rejects_non_list_segments(tmp_path):
    with pytest.raises(TypeError):
        TranscriptManager.save("invalid", str(tmp_path / "sample.json"))


def test_save_rejects_invalid_timestamps(tmp_path):
    segments = [{"start": 3, "end": 2, "text": "مرحبا"}]

    with pytest.raises(ValueError):
        TranscriptManager.save(segments, str(tmp_path / "sample.json"))


def test_save_rejects_missing_fields(tmp_path):
    segments = [{"start": 0, "end": 2}]

    with pytest.raises(ValueError):
        TranscriptManager.save(segments, str(tmp_path / "sample.json"))


def test_save_rejects_non_string_text(tmp_path):
    segments = [{"start": 0, "end": 2, "text": 123}]

    with pytest.raises(TypeError):
        TranscriptManager.save(segments, str(tmp_path / "sample.json"))
