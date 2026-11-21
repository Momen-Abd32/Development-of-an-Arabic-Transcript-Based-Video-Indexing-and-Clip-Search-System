import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class AudioExtractor:
    """Prepare mono 16 kHz WAV audio from video or standalone audio media."""

    @staticmethod
    def prepare(media_path: str, output_path: str) -> Path:
        """Convert an audio or video file to mono 16 kHz WAV for transcription."""
        media = Path(media_path)
        output = Path(output_path)

        if not media.exists():
            raise FileNotFoundError(f"Media file not found: {media}")

        if not media.is_file():
            raise ValueError("Media path must point to a file.")

        if media.resolve() == output.resolve():
            raise ValueError("Input media and normalized audio paths must be different.")

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError("FFmpeg is not installed or not available in PATH.")

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None

        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{output.stem}.",
                suffix=output.suffix or ".wav",
                dir=output.parent,
            )
            os.close(file_descriptor)
            temporary_path = Path(temporary_name)

            command = [
                ffmpeg_path,
                "-nostdin",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", str(media),
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-c:a", "pcm_s16le",
                str(temporary_path),
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Audio preparation failed:\\n{result.stderr.strip()}"
                )

            if not temporary_path.exists() or temporary_path.stat().st_size == 0:
                raise RuntimeError("Prepared audio file is empty.")

            os.replace(temporary_path, output)
            return output
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def extract(video_path: str, output_path: str) -> Path:
        """Backward-compatible alias for extracting audio from a video."""
        return AudioExtractor.prepare(video_path, output_path)
