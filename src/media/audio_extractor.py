import subprocess
import shutil
from pathlib import Path


class AudioExtractor:
    """Extract mono 16 kHz WAV audio from a video file."""

    @staticmethod
    def prepare(media_path: str, output_path: str) -> Path:
        """Convert an audio or video file to mono 16 kHz WAV for transcription."""
        media = Path(media_path)
        output = Path(output_path)

        if not media.exists():
            raise FileNotFoundError(f"Media file not found: {media}")

        if not media.is_file():
            raise ValueError("Media path must point to a file.")

        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "FFmpeg is not installed or not available in PATH."
            )

        output.parent.mkdir(parents=True, exist_ok=True)

        command = [
            "ffmpeg",
            "-y",
            "-i", str(media),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            str(output),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Audio extraction failed:\n{result.stderr}"
            )

        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError("Extracted audio file is empty.")

        return output