import math
import shutil
import subprocess
from pathlib import Path


class ClipManager:

    def __init__(self, output_dir="exports/clips"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_clip(
        self,
        video_path: str,
        start: float,
        end: float,
        output_name: str,
    ) -> Path:

        video = Path(video_path)

        if not video.exists():
            raise FileNotFoundError(f"Video not found: {video}")

        if not video.is_file():
            raise ValueError("Video path must point to a file.")

        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "FFmpeg is not installed or not available in PATH."
            )

        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
            or not math.isfinite(start)
            or not math.isfinite(end)
        ):
            raise TypeError("Clip timestamps must be finite numbers.")

        if start < 0 or end <= start:
            raise ValueError("Invalid clip timestamps.")

        if not isinstance(output_name, str) or not output_name.strip():
            raise ValueError("Output name cannot be empty.")

        if Path(output_name).name != output_name:
            raise ValueError("Output name must not contain a directory path.")

        if output_name in (".", ".."):
            raise ValueError("Invalid output name.")

        if not output_name.lower().endswith(".mp4"):
            output_name += ".mp4"

        output_path = self.output_dir / output_name

        command = [
            "ffmpeg",
            "-y",
            "-ss", str(start),
            "-i", str(video),
            "-t", str(end - start),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-avoid_negative_ts", "make_zero",
            str(output_path),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Clip creation failed:\n{result.stderr}"
            )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Created clip is empty.")

        return output_path
    def create_audio_clip(
        self,
        audio_path: str,
        start: float,
        end: float,
        output_name: str,
    ) -> Path:
        """Extract a timestamped audio-only clip from an audio source."""
        audio = Path(audio_path)
        if not audio.is_file():
            raise FileNotFoundError(f"Audio not found: {audio}")
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "FFmpeg is not installed or not available in PATH."
            )
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
            or not math.isfinite(start)
            or not math.isfinite(end)
        ):
            raise TypeError("Clip timestamps must be finite numbers.")
        if start < 0 or end <= start:
            raise ValueError("Invalid clip timestamps.")
        if (
            not isinstance(output_name, str)
            or not output_name.strip()
            or Path(output_name).name != output_name
            or output_name in (".", "..")
        ):
            raise ValueError("Invalid output name.")
        if not output_name.lower().endswith(".m4a"):
            output_name += ".m4a"

        output_path = self.output_dir / output_name
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-i",
            str(audio),
            "-t",
            str(end - start),
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Audio clip creation failed:\\n{result.stderr}"
            )
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Created audio clip is empty.")
        return output_path
