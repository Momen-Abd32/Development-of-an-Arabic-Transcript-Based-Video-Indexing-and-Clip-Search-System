
import subprocess
import pytest

from src.clips.clip_manager import ClipManager


def setup_ffmpeg(monkeypatch, output_path, returncode=0, stderr=""):
    monkeypatch.setattr(
        "src.clips.clip_manager.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        if returncode == 0:
            output_path.write_bytes(b"fake video clip")

        return subprocess.CompletedProcess(
            command, returncode, "", stderr
        )

    monkeypatch.setattr(
        "src.clips.clip_manager.subprocess.run",
        fake_run,
    )


def test_create_clip_success(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    output_dir = tmp_path / "clips"
    output_path = output_dir / "sample.mp4"

    setup_ffmpeg(monkeypatch, output_path)

    manager = ClipManager(str(output_dir))
    result = manager.create_clip(
        str(video), 1.5, 5.5, "sample"
    )

    assert result == output_path
    assert result.exists()
    assert result.stat().st_size > 0


def test_create_clip_adds_mp4_extension(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    output_dir = tmp_path / "clips"
    output_path = output_dir / "clip.mp4"

    setup_ffmpeg(monkeypatch, output_path)

    manager = ClipManager(str(output_dir))
    result = manager.create_clip(
        str(video), 0, 3, "clip"
    )

    assert result.suffix == ".mp4"


def test_missing_video_raises_error(tmp_path, monkeypatch):
    manager = ClipManager(str(tmp_path / "clips"))

    with pytest.raises(FileNotFoundError):
        manager.create_clip(
            str(tmp_path / "missing.mp4"), 0, 2, "clip"
        )


def test_directory_instead_of_video_raises_error(tmp_path, monkeypatch):
    manager = ClipManager(str(tmp_path / "clips"))

    with pytest.raises(ValueError, match="file"):
        manager.create_clip(
            str(tmp_path), 0, 2, "clip"
        )


def test_missing_ffmpeg_raises_error(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    monkeypatch.setattr(
        "src.clips.clip_manager.shutil.which",
        lambda name: None,
    )

    manager = ClipManager(str(tmp_path / "clips"))

    with pytest.raises(RuntimeError, match="FFmpeg"):
        manager.create_clip(str(video), 0, 2, "clip")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (-1, 2),
        (3, 2),
        (2, 2),
    ],
)
def test_invalid_timestamps_raise_error(tmp_path, monkeypatch, start, end):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    monkeypatch.setattr(
        "src.clips.clip_manager.shutil.which",
        lambda name: "ffmpeg",
    )

    manager = ClipManager(str(tmp_path / "clips"))

    with pytest.raises(ValueError, match="timestamps"):
        manager.create_clip(str(video), start, end, "clip")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (True, 2),
        (0, False),
        (float("nan"), 2),
        (0, float("inf")),
    ],
)
def test_non_finite_or_non_numeric_timestamps_raise_error(
    tmp_path, monkeypatch, start, end
):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    monkeypatch.setattr(
        "src.clips.clip_manager.shutil.which",
        lambda name: "ffmpeg",
    )

    manager = ClipManager(str(tmp_path / "clips"))

    with pytest.raises(TypeError, match="finite numbers"):
        manager.create_clip(str(video), start, end, "clip")


@pytest.mark.parametrize("name", ["", "   ", "../outside", "folder/clip", ".", ".."])
def test_invalid_output_names_raise_error(tmp_path, monkeypatch, name):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    monkeypatch.setattr(
        "src.clips.clip_manager.shutil.which",
        lambda name: "ffmpeg",
    )

    manager = ClipManager(str(tmp_path / "clips"))

    with pytest.raises(ValueError):
        manager.create_clip(str(video), 0, 2, name)


def test_ffmpeg_failure_raises_error(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    output_path = tmp_path / "clips" / "clip.mp4"
    setup_ffmpeg(
        monkeypatch, output_path,
        returncode=1,
        stderr="FFmpeg failed",
    )

    manager = ClipManager(str(tmp_path / "clips"))

    with pytest.raises(RuntimeError, match="FFmpeg failed"):
        manager.create_clip(str(video), 0, 2, "clip")


def test_empty_clip_raises_error(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    output_dir = tmp_path / "clips"
    output_path = output_dir / "clip.mp4"

    monkeypatch.setattr(
        "src.clips.clip_manager.shutil.which",
        lambda name: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "src.clips.clip_manager.subprocess.run",
        fake_run,
    )

    manager = ClipManager(str(output_dir))

    with pytest.raises(RuntimeError, match="empty"):
        manager.create_clip(str(video), 0, 2, "clip")
