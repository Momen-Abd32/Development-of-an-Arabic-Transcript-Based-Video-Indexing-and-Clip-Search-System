import csv
from pathlib import Path


class ClipExporter:

    FIELDS = [
        "id",
        "video_id",
        "clip_path",
        "start",
        "end",
        "duration",
        "notes",
        "created_at",
    ]

    @staticmethod
    def export_csv(
        clips: list[dict],
        output_path: str = "exports/clips_list.csv",
    ) -> Path:

        if not isinstance(clips, list):
            raise TypeError("Clips must be a list.")

        for index, clip in enumerate(clips):
            if not isinstance(clip, dict):
                raise TypeError(
                    f"Clip {index} must be a dictionary."
                )

            missing = [
                field for field in ClipExporter.FIELDS
                if field not in clip
            ]

            if missing:
                raise ValueError(
                    f"Clip {index} is missing fields: {missing}"
                )

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=ClipExporter.FIELDS,
                extrasaction="ignore",
            )

            writer.writeheader()

            for clip in clips:
                writer.writerow({
                    field: clip[field]
                    for field in ClipExporter.FIELDS
                })

        return output