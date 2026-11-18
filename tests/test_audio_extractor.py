import subprocess
import pytest

from src.media.audio_extractor import AudioExtractor


def test_extract_audio_success(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    output = tmp_path / "audio" / "output.wav"

    monkeypatch.setattr(
        "src.media.audio_extractor.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        output.write_bytes(b"fake audio")
        return subprocess.CompletedProcess(
            command, 0, "", ""
        )

    monkeypatch.setattr(
        "src.media.audio_extractor.subprocess.run",
        fake_run,
    )

    result = AudioExtractor.extract(str(video), str(output))

    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_extract_missing_video_raises_error(tmp_path):
    video = tmp_path / "missing.mp4"
    output = tmp_path / "audio.wav"

    with pytest.raises(FileNotFoundError):
        AudioExtractor.extract(str(video), str(output))


def test_extract_directory_instead_of_video_raises_error(tmp_path):
    output = tmp_path / "audio.wav"

    with pytest.raises(ValueError):
        AudioExtractor.extract(str(tmp_path), str(output))


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


def test_extract_ffmpeg_failure_raises_error(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    monkeypatch.setattr(
        "src.media.audio_extractor.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 1, "", "FFmpeg error"
        )

    monkeypatch.setattr(
        "src.media.audio_extractor.subprocess.run",
        fake_run,
    )

    with pytest.raises(RuntimeError, match="FFmpeg error"):
        AudioExtractor.extract(
            str(video),
            str(tmp_path / "audio.wav"),
        )


def test_extract_empty_output_raises_error(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    output = tmp_path / "audio.wav"

    monkeypatch.setattr(
        "src.media.audio_extractor.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        output.write_bytes(b"")
        return subprocess.CompletedProcess(
            command, 0, "", ""
        )

    monkeypatch.setattr(
        "src.media.audio_extractor.subprocess.run",
        fake_run,
    )

    with pytest.raises(RuntimeError, match="empty"):
        AudioExtractor.extract(str(video), str(output))
