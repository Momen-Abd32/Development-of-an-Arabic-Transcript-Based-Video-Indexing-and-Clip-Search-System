import subprocess
from pathlib import Path

import pytest

from src.media.keyframe_extractor import KeyframeExtractor


def _write_frame(command):
    output_pattern = Path(command[-1])
    output_pattern.parent.mkdir(parents=True, exist_ok=True)
    output_pattern.with_name("keyframe_000001.jpg").write_bytes(b"frame")


def test_extracts_keyframes_and_replaces_previous_output(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "keyframes"
    output.mkdir()
    (output / "old.jpg").write_bytes(b"old")

    monkeypatch.setattr(
        "src.media.keyframe_extractor.shutil.which",
        lambda name: "ffmpeg",
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        _write_frame(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "src.media.keyframe_extractor.subprocess.run",
        fake_run,
    )

    frames = KeyframeExtractor.extract(
        video,
        output,
        interval_seconds=15,
        max_frames=8,
        width=480,
    )

    assert len(frames) == 1
    assert frames[0].read_bytes() == b"frame"
    assert not (output / "old.jpg").exists()
    assert captured["command"][captured["command"].index("-frames:v") + 1] == "8"
    assert "fps=1/15" in captured["command"][captured["command"].index("-vf") + 1]


def test_failed_extraction_preserves_existing_keyframes(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "keyframes"
    output.mkdir()
    previous = output / "keyframe_000001.jpg"
    previous.write_bytes(b"previous")

    monkeypatch.setattr(
        "src.media.keyframe_extractor.shutil.which",
        lambda name: "ffmpeg",
    )
    monkeypatch.setattr(
        "src.media.keyframe_extractor.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, "", "decode error"
        ),
    )

    with pytest.raises(RuntimeError, match="decode error"):
        KeyframeExtractor.extract(video, output)

    assert previous.read_bytes() == b"previous"
    assert not list(tmp_path.glob(".keyframes.*"))


def test_rejects_missing_video(tmp_path):
    with pytest.raises(FileNotFoundError):
        KeyframeExtractor.extract(tmp_path / "missing.mp4", tmp_path / "frames")


@pytest.mark.parametrize("interval", [0, -1, float("inf"), True])
def test_rejects_invalid_interval(tmp_path, interval):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")

    with pytest.raises((TypeError, ValueError)):
        KeyframeExtractor.extract(video, tmp_path / "frames", interval_seconds=interval)


def test_rejects_invalid_frame_limit_and_width(tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")

    with pytest.raises(ValueError):
        KeyframeExtractor.extract(video, tmp_path / "frames", max_frames=0)

    with pytest.raises(ValueError):
        KeyframeExtractor.extract(video, tmp_path / "frames", width=0)


def test_requires_ffmpeg(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        "src.media.keyframe_extractor.shutil.which",
        lambda name: None,
    )

    with pytest.raises(RuntimeError, match="FFmpeg"):
        KeyframeExtractor.extract(video, tmp_path / "frames")


def test_extract_returns_ffmpeg_timestamps_when_requested(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "keyframes"
    monkeypatch.setattr(
        "src.media.keyframe_extractor.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        _write_frame(command)
        stderr = (
            "[Parsed_showinfo] n: 0 pts: 0 pts_time:0.000000 "
            "pos: 0 fmt:yuv420p\n"
        )
        return subprocess.CompletedProcess(command, 0, "", stderr)

    monkeypatch.setattr(
        "src.media.keyframe_extractor.subprocess.run",
        fake_run,
    )
    frames = KeyframeExtractor.extract(
        video, output, return_timestamps=True
    )
    assert len(frames) == 1
    assert frames[0][0].is_file()
    assert frames[0][1] == 0.0


def test_timestamp_mode_rejects_missing_ffmpeg_timestamps(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "keyframes"
    monkeypatch.setattr(
        "src.media.keyframe_extractor.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        _write_frame(command)
        return subprocess.CompletedProcess(command, 0, "", "no timestamps")

    monkeypatch.setattr(
        "src.media.keyframe_extractor.subprocess.run",
        fake_run,
    )
    with pytest.raises(RuntimeError, match="timestamp"):
        KeyframeExtractor.extract(
            video, output, return_timestamps=True
        )
    assert not output.exists()
