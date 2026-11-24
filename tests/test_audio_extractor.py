import subprocess
from pathlib import Path

import pytest

from src.media.audio_extractor import AudioExtractor


def _temporary_output(command):
    return Path(command[-1])


def test_extract_audio_success(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")
    output = tmp_path / "audio" / "output.wav"

    monkeypatch.setattr(
        "src.media.audio_extractor.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        _temporary_output(command).write_bytes(b"fake audio")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "src.media.audio_extractor.subprocess.run",
        fake_run,
    )

    result = AudioExtractor.extract(str(video), str(output))

    assert result == output
    assert output.read_bytes() == b"fake audio"
    assert not list(output.parent.glob(".output.*.wav"))


def test_extract_missing_video_raises_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        AudioExtractor.extract(
            str(tmp_path / "missing.mp4"),
            str(tmp_path / "audio.wav"),
        )


def test_extract_directory_instead_of_video_raises_error(tmp_path):
    with pytest.raises(ValueError, match="file"):
        AudioExtractor.extract(
            str(tmp_path),
            str(tmp_path / "audio.wav"),
        )


def test_prepare_rejects_same_input_and_output_path(tmp_path):
    media = tmp_path / "recording.wav"
    media.write_bytes(b"original")

    with pytest.raises(ValueError, match="different"):
        AudioExtractor.prepare(str(media), str(media))

    assert media.read_bytes() == b"original"


def test_extract_without_ffmpeg_raises_error(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    monkeypatch.setattr(
        "src.media.audio_extractor.shutil.which",
        lambda name: None,
    )

    with pytest.raises(RuntimeError, match="FFmpeg"):
        AudioExtractor.extract(
            str(video),
            str(tmp_path / "audio.wav"),
        )


def test_extract_ffmpeg_failure_preserves_existing_output(
    tmp_path,
    monkeypatch,
):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")
    output = tmp_path / "audio.wav"
    output.write_bytes(b"previous valid audio")

    monkeypatch.setattr(
        "src.media.audio_extractor.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "FFmpeg error")

    monkeypatch.setattr(
        "src.media.audio_extractor.subprocess.run",
        fake_run,
    )

    with pytest.raises(RuntimeError, match="FFmpeg error"):
        AudioExtractor.extract(str(video), str(output))

    assert output.read_bytes() == b"previous valid audio"
    assert not list(tmp_path.glob(".audio.*.wav"))


def test_extract_empty_output_raises_error(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    monkeypatch.setattr(
        "src.media.audio_extractor.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        _temporary_output(command).write_bytes(b"")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "src.media.audio_extractor.subprocess.run",
        fake_run,
    )

    with pytest.raises(RuntimeError, match="empty"):
        AudioExtractor.extract(
            str(video),
            str(tmp_path / "audio.wav"),
        )


def test_prepare_normalizes_standalone_audio_file(tmp_path, monkeypatch):
    audio = tmp_path / "recording.mp3"
    audio.write_bytes(b"fake audio")
    output = tmp_path / "normalized" / "recording.wav"
    captured = {}

    monkeypatch.setattr(
        "src.media.audio_extractor.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        _temporary_output(command).write_bytes(b"normalized wav")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "src.media.audio_extractor.subprocess.run",
        fake_run,
    )

    result = AudioExtractor.prepare(str(audio), str(output))

    assert result == output
    assert output.read_bytes() == b"normalized wav"
    assert "-nostdin" in captured["command"]
    assert captured["command"][captured["command"].index("-i") + 1] == str(audio)
    assert captured["command"][captured["command"].index("-ar") + 1] == "16000"
