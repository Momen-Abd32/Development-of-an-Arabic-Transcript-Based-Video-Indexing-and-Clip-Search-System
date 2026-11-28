import pytest
from types import SimpleNamespace

from src.transcription.speaker_diarizer import PyannoteSpeakerDiarizer

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



@pytest.mark.parametrize(
    "turn",
    [
        {"start": float("nan"), "end": 2, "speaker": "SPEAKER_00"},
        {"start": 0, "end": float("inf"), "speaker": "SPEAKER_00"},
        {"start": True, "end": 2, "speaker": "SPEAKER_00"},
        {"start": 0, "end": 2, "speaker": "  "},
        {"start": 0, "speaker": "SPEAKER_00"},
    ],
)
def test_rejects_non_finite_or_malformed_speaker_turns(turn):
    with pytest.raises((ValueError, TypeError)):
        apply_speaker_turns(
            [{"start": 0, "end": 1, "text": "نص"}],
            [turn],
        )


@pytest.mark.parametrize("start,end", [
    (float("nan"), 2),
    (0, float("inf")),
    (True, 2),
])
def test_rejects_non_finite_or_boolean_transcript_timestamps(start, end):
    with pytest.raises(ValueError):
        apply_speaker_turns(
            [{"start": start, "end": end, "text": "نص"}],
            [],
        )


def test_preserves_original_transcript_and_existing_metadata():
    segment = {"start": 0, "end": 1, "text": "إزيك؟", "confidence": 0.92}
    result = apply_speaker_turns([segment], [])

    assert result[0]["text"] == "إزيك؟"
    assert result[0]["confidence"] == 0.92
    assert result[0]["speaker"] == "UNKNOWN"
    assert "speaker" not in segment



def test_diarizer_requires_token_before_loading_optional_dependency(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="HF_TOKEN"):
        PyannoteSpeakerDiarizer()


def test_diarize_converts_pyannote_turns_to_plain_timestamp_records(tmp_path):
    class FakeTurn:
        start = 1.25
        end = 2.75

    class FakeAnnotation:
        def itertracks(self, yield_label=False):
            assert yield_label is True
            yield FakeTurn(), None, "SPEAKER_02"

    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")
    diarizer = PyannoteSpeakerDiarizer.__new__(PyannoteSpeakerDiarizer)
    diarizer.pipeline = lambda _: SimpleNamespace(speaker_diarization=FakeAnnotation())

    assert diarizer.diarize(str(audio)) == [
        {"start": 1.25, "end": 2.75, "speaker": "SPEAKER_02"}
    ]


def test_diarize_rejects_missing_audio_file():
    diarizer = PyannoteSpeakerDiarizer.__new__(PyannoteSpeakerDiarizer)
    diarizer.pipeline = lambda _: None

    with pytest.raises(ValueError, match="missing or empty"):
        diarizer.diarize("missing-audio.wav")
