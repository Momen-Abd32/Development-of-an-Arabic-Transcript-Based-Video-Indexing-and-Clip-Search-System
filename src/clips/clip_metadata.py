import json
import math
from pathlib import Path
from datetime import datetime


class ClipMetadata:

    def __init__(self, metadata_path="data/database/clips.json"):
        self.metadata_path = Path(metadata_path)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.metadata_path.exists():
            self._write([])

    def _write(self, clips: list[dict]) -> None:
        temporary_path = self.metadata_path.with_suffix(".tmp")

        temporary_path.write_text(
            json.dumps(clips, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )

        temporary_path.replace(self.metadata_path)

    def load(self) -> list[dict]:
        try:
            clips = json.loads(
                self.metadata_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as error:
            raise ValueError("Clip metadata file contains invalid JSON.") from error

        if not isinstance(clips, list):
            raise ValueError("Clip metadata must contain a list.")

        return clips

    def save_clip(
        self,
        video_id: str,
        clip_path: str,
        start: float,
        end: float,
        notes: str = "",
    ) -> dict:

        if not isinstance(video_id, str) or not video_id.strip():
            raise ValueError("Video ID cannot be empty.")

        if not isinstance(clip_path, str) or not clip_path.strip():
            raise ValueError("Clip path cannot be empty.")

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

        if not isinstance(notes, str):
            raise TypeError("Notes must be a string.")

        clips = self.load()

        # A video segment represents one logical clip. Reuse its metadata
        # instead of creating duplicate entries when the user saves it again.
        for existing_clip in clips:
            if (
                existing_clip.get("video_id") == video_id
                and existing_clip.get("start") == start
                and existing_clip.get("end") == end
            ):
                return existing_clip

        next_id = max(
            (
                clip.get("id", 0)
                for clip in clips
                if isinstance(clip.get("id", 0), int)
                and not isinstance(clip.get("id", 0), bool)
            ),
            default=0,
        ) + 1

        clip = {
            "id": next_id,
            "video_id": video_id,
            "clip_path": clip_path,
            "start": start,
            "end": end,
            "duration": round(end - start, 2),
            "notes": notes,
            "created_at": datetime.now().isoformat(
                timespec="seconds"
            ),
        }

        clips.append(clip)
        self._write(clips)

        return clip

    def get_all_clips(self) -> list[dict]:
        return self.load()
