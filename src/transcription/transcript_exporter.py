import csv
from pathlib import Path

from src.transcription.transcript_manager import TranscriptManager


class TranscriptExporter:

    @staticmethod
    def export_csv(
        segments: list[dict],
        output_path: str,
        video_id: str = "",
    ) -> Path:

        TranscriptManager._validate_segments(segments)

        if not isinstance(video_id, str):
            raise TypeError("Video ID must be a string.")

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "video_id",
                    "start",
                    "end",
                    "text",
                ],
            )

            writer.writeheader()

            for segment in segments:
                writer.writerow({
                    "video_id": video_id,
                    "start": segment["start"],
                    "end": segment["end"],
                    "text": segment["text"],
                })

        return output