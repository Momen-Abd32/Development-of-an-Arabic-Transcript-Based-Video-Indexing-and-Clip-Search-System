
import pytest
from types import SimpleNamespace

from src.transcription.faster_whisper_engine import FasterWhisperEngine


def test_invalid_device_raises_error(monkeypatch):
    def fake_model(*args, **kwargs):
        raise AssertionError("Model should not be initialized.")

    monkeypatch.setattr(
        "src.transcription.faster_whisper_engine.WhisperModel",
        fake_model,
    )

    with pytest.raises(ValueError, match="Device"):
        FasterWhisperEngine(device="invalid")


def test_model_initialization(monkeypatch):
    calls = {}

    def fake_model(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(
        "src.transcription.faster_whisper_engine.WhisperModel",
        fake_model,
    )

    engine = FasterWhisperEngine()

    assert engine.model is not None
    assert calls["args"] == ("tiny",)
    assert calls["kwargs"]["device"] == "cpu"
    assert calls["kwargs"]["compute_type"] == "int8"


def test_missing_audio_raises_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.transcription.faster_whisper_engine.WhisperModel",
        lambda *args, **kwargs: object(),
    )

    engine = FasterWhisperEngine()

    with pytest.raises(FileNotFoundError):
        engine.transcribe(str(tmp_path / "missing.wav"))


def test_empty_audio_raises_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.transcription.faster_whisper_engine.WhisperModel",
        lambda *args, **kwargs: object(),
    )

    engine = FasterWhisperEngine()
    audio = tmp_path / "empty.wav"
    audio.write_bytes(b"")

    with pytest.raises(ValueError, match="empty or invalid"):
        engine.transcribe(str(audio))


def test_transcribe_returns_valid_segments(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake audio")

    fake_segments = [
        SimpleNamespace(start=0.123, end=2.456, text=" مرحبا بالعالم "),
        SimpleNamespace(start=2.5, end=3.75, text=" كيف حالك "),
    ]

    class FakeModel:
        def transcribe(self, *args, **kwargs):
            return iter(fake_segments), object()

    monkeypatch.setattr(
        "src.transcription.faster_whisper_engine.WhisperModel",
        lambda *args, **kwargs: FakeModel(),
    )

    engine = FasterWhisperEngine()
    results = engine.transcribe(str(audio))

    assert len(results) == 2
    assert results[0] == {
        "start": 0.12,
        "end": 2.46,
        "text": "مرحبا بالعالم",
    }
    assert results[1] == {
        "start": 2.5,
        "end": 3.75,
        "text": "كيف حالك",
    }


def test_transcribe_filters_empty_and_invalid_segments(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake audio")

    fake_segments = [
        SimpleNamespace(start=0, end=1, text="   "),
        SimpleNamespace(start=-1, end=1, text="invalid start"),
        SimpleNamespace(start=2, end=2, text="invalid duration"),
        SimpleNamespace(start=3, end=4, text=" valid text "),
    ]

    class FakeModel:
        def transcribe(self, *args, **kwargs):
            return iter(fake_segments), object()

    monkeypatch.setattr(
        "src.transcription.faster_whisper_engine.WhisperModel",
        lambda *args, **kwargs: FakeModel(),
    )

    engine = FasterWhisperEngine()
    results = engine.transcribe(str(audio))

    assert results == [
        {
            "start": 3,
            "end": 4,
            "text": "valid text",
        }
    ]


def test_transcribe_uses_arabic_settings(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake audio")

    calls = {}

    class FakeModel:
        def transcribe(self, path, **kwargs):
            calls["path"] = path
            calls["kwargs"] = kwargs
            return iter([]), object()

    monkeypatch.setattr(
        "src.transcription.faster_whisper_engine.WhisperModel",
        lambda *args, **kwargs: FakeModel(),
    )

    engine = FasterWhisperEngine()
    engine.transcribe(str(audio))

    assert calls["kwargs"]["language"] == "ar"
    assert calls["kwargs"]["task"] == "transcribe"
    assert calls["kwargs"]["beam_size"] == 1
    assert calls["kwargs"]["best_of"] == 1
    assert calls["kwargs"]["vad_filter"] is True
    assert calls["kwargs"]["condition_on_previous_text"] is False
