import pytest

from src.transcription.speaker_diarizer import apply_speaker_turns


def test_assigns_speaker_by_greatest_time_overlap():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "مرحبا"},
        {"start": 2.0, "end": 4.0, "text": "أهلا"},
    ]
    turns = [
        {"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"},
        {"start": 1.5, "end": 4.0, "speaker": "SPEAKER_01"},
    ]

    result = apply_speaker_turns(segments, turns)

    assert result[0]["speaker"] == "SPEAKER_00"
    assert result[1]["speaker"] == "SPEAKER_01"
    assert result[0]["text"] == "مرحبا"


def test_marks_segments_without_speaker_overlap_unknown():
    result = apply_speaker_turns(
        [{"start": 5.0, "end": 6.0, "text": "نص"}],
        [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}],
    )

    assert result[0]["speaker"] == "UNKNOWN"


def test_rejects_invalid_speaker_turn():
    with pytest.raises(ValueError):
        apply_speaker_turns(
            [{"start": 0.0, "end": 1.0, "text": "نص"}],
            [{"start": 2.0, "end": 1.0, "speaker": "SPEAKER_00"}],
        )


def test_rejects_invalid_transcript_timestamps():
    with pytest.raises(ValueError):
        apply_speaker_turns(
            [{"start": 1.0, "end": 1.0, "text": "نص"}],
            [],
        )
