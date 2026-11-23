"""Extract timestamped video keyframes using the system FFmpeg binary."""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


class KeyframeExtractor:
    """Create a replaceable directory of sampled JPEG keyframes."""

    @staticmethod
    def extract(
        video_path: str | Path,
        output_dir: str | Path,
        interval_seconds: float = 30,
        max_frames: int = 100,
        width: int = 640,
    ) -> list[Path]:
        source = Path(video_path)
        output = Path(output_dir)

        if not source.exists():
            raise FileNotFoundError(f"Video file not found: {source}")
        if not source.is_file():
            raise ValueError("Video path must point to a file.")
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (int, float)):
            raise TypeError("Frame interval must be a number.")
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("Frame interval must be a positive finite number.")
        if isinstance(max_frames, bool) or not isinstance(max_frames, int) or max_frames <= 0:
            raise ValueError("Maximum frame count must be a positive integer.")
        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            raise ValueError("Frame width must be a positive integer.")
        if output.exists() and not output.is_dir():
            raise ValueError("Keyframe output path must be a directory.")

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError("FFmpeg is not installed or not available in PATH.")

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(tempfile.mkdtemp(
            prefix=f".{output.name}.",
            dir=output.parent,
        ))
        backup_dir = output.parent / f".{output.name}.backup-{uuid.uuid4().hex}"

        try:
            pattern = temporary_dir / "keyframe_%06d.jpg"
            command = [
                ffmpeg_path,
                "-nostdin",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", str(source),
                "-vf", f"fps=1/{interval_seconds},scale='min({width},iw)':-2",
                "-frames:v", str(max_frames),
                "-q:v", "2",
                str(pattern),
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"Keyframe extraction failed:\n{result.stderr.strip()}"
                )

            staged_frames = sorted(temporary_dir.glob("keyframe_*.jpg"))
            if not staged_frames:
                raise RuntimeError("FFmpeg completed without producing keyframes.")

            had_previous_output = output.exists()
            if had_previous_output:
                os.replace(output, backup_dir)
            try:
                os.replace(temporary_dir, output)
            except Exception:
                if had_previous_output and backup_dir.exists():
                    os.replace(backup_dir, output)
                raise

            if backup_dir.exists():
                shutil.rmtree(backup_dir)

            return sorted(output.glob("keyframe_*.jpg"))
        finally:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir)
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
