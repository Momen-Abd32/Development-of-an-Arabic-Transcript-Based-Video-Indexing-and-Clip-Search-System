import json
import math
import os
import tempfile
from pathlib import Path


class TranscriptManager:

    @staticmethod
    def _validate_segments(segments: list[dict]) -> None:
        if not isinstance(segments, list):
            raise TypeError("Segments must be a list.")

        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                raise TypeError(
                    f"Segment {index} must be a dictionary."
                )

            if not all(key in segment for key in ("start", "end", "text")):
                raise ValueError(
                    f"Segment {index} is missing required fields."
                )

            start = segment["start"]
            end = segment["end"]
            text = segment["text"]

            if (
                isinstance(start, bool)
                or not isinstance(start, (int, float))
                or isinstance(end, bool)
                or not isinstance(end, (int, float))
            ):
                raise TypeError(
                    f"Segment {index} timestamps must be numbers."
                )

            if not math.isfinite(start) or not math.isfinite(end):
                raise ValueError(
                    f"Segment {index} timestamps must be finite numbers."
                )

            if start < 0 or end <= start:
                raise ValueError(
                    f"Segment {index} has invalid timestamps."
                )

            if not isinstance(text, str):
                raise TypeError(
                    f"Segment {index} text must be a string."
                )

    @staticmethod
    def save(segments: list[dict], output_path: str) -> Path:
        TranscriptManager._validate_segments(segments)

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "segments": segments,
            "total_segments": len(segments),
        }
        serialized = json.dumps(data, ensure_ascii=False, indent=4)

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output.parent,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(serialized)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, output)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

        return output

    @staticmethod
    def load(input_path: str) -> list[dict]:
        input_file = Path(input_path)

        if not input_file.exists():
            raise FileNotFoundError(
                f"Transcript not found: {input_file}"
            )

        data = json.loads(
            input_file.read_text(encoding="utf-8")
        )

        if not isinstance(data, dict) or "segments" not in data:
            raise ValueError("Invalid transcript file format.")

        segments = data["segments"]
        TranscriptManager._validate_segments(segments)

        return segments
