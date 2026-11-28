"""Real FFmpeg integration tests for exported video and audio clips."""
import json
import shutil
import subprocess

import pytest

from src.clips.clip_manager import ClipManager


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and ffprobe are required for media integration tests.",
)


def _run(command):
    subprocess.run(command, check=True, capture_output=True, text=True)


def _duration(path):
    output = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(output.stdout)["format"]["duration"])


def test_create_video_clip_with_real_ffmpeg(tmp_path):
    source = tmp_path / "source.mp4"
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=25",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(source),
    ])

    clip = ClipManager(str(tmp_path / "clips")).create_clip(
        str(source), 0.5, 1.5, "integration-video"
    )

    assert clip.is_file()
    assert clip.stat().st_size > 0
    assert clip.suffix == ".mp4"
    assert 0.8 <= _duration(clip) <= 1.3


def test_create_audio_clip_with_real_ffmpeg(tmp_path):
    source = tmp_path / "source.wav"
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=3",
        str(source),
    ])

    clip = ClipManager(str(tmp_path / "clips")).create_audio_clip(
        str(source), 0.5, 1.5, "integration-audio"
    )

    assert clip.is_file()
    assert clip.stat().st_size > 0
    assert clip.suffix == ".m4a"
    assert 0.8 <= _duration(clip) <= 1.3
