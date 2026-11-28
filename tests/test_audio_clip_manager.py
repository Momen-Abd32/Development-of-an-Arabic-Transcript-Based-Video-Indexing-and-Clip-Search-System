import subprocess

import pytest

from src.clips.clip_manager import ClipManager


def test_create_audio_clip_success_and_uses_audio_only_codec(tmp_path, monkeypatch):
    source = tmp_path / "episode.wav"
    source.write_bytes(b"fake audio")
    output = tmp_path / "clips" / "sample.m4a"
    captured = {}

    monkeypatch.setattr("src.clips.clip_manager.shutil.which", lambda name: "ffmpeg")

    def fake_run(command, **kwargs):
        captured["command"] = command
        output.write_bytes(b"fake m4a")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("src.clips.clip_manager.subprocess.run", fake_run)
    result = ClipManager(str(output.parent)).create_audio_clip(
        str(source), 2.0, 5.5, "sample"
    )

    assert result == output
    assert "-vn" in captured["command"]
    assert "aac" in captured["command"]
    assert result.read_bytes() == b"fake m4a"


def test_create_audio_clip_rejects_invalid_timestamps(tmp_path, monkeypatch):
    source = tmp_path / "episode.wav"
    source.write_bytes(b"fake audio")
    monkeypatch.setattr("src.clips.clip_manager.shutil.which", lambda name: "ffmpeg")
    manager = ClipManager(str(tmp_path / "clips"))

    with pytest.raises(ValueError, match="timestamps"):
        manager.create_audio_clip(str(source), 3, 2, "bad")


def test_create_audio_clip_requires_ffmpeg(tmp_path, monkeypatch):
    source = tmp_path / "episode.wav"
    source.write_bytes(b"fake audio")
    monkeypatch.setattr("src.clips.clip_manager.shutil.which", lambda name: None)
    manager = ClipManager(str(tmp_path / "clips"))

    with pytest.raises(RuntimeError, match="FFmpeg"):
        manager.create_audio_clip(str(source), 0, 1, "clip")
