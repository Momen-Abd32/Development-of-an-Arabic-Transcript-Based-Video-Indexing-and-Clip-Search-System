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
        ):
            raise TypeError("Clip timestamps must be finite numbers.")

        try:
            timestamps_are_finite = math.isfinite(start) and math.isfinite(end)
        except OverflowError:
            timestamps_are_finite = False

        if not timestamps_are_finite:
            raise TypeError("Clip timestamps must be finite numbers.")

        if start < 0 or end <= start:
            raise ValueError("Invalid clip timestamps.")

        if not isinstance(notes, str):
            raise TypeError("Notes must be a string.")

        clips = self.load()

        # Re-saving the same video segment updates its existing metadata.
        # Keep the first record's ID and creation timestamp, and remove any
        # legacy duplicates for the same video and time range.
        matching_clips = [
            clip
            for clip in clips
            if isinstance(clip, dict)
            and clip.get("video_id") == video_id
            and clip.get("start") == start
            and clip.get("end") == end
        ]

        if matching_clips:
            existing_clip = matching_clips[0]
            existing_clip["clip_path"] = clip_path
            existing_clip["notes"] = notes

            deduplicated_clips = []
            kept_existing_clip = False

            for clip in clips:
                if (
                    isinstance(clip, dict)
                    and clip.get("video_id") == video_id
                    and clip.get("start") == start
                    and clip.get("end") == end
                ):
                    if kept_existing_clip:
                        continue
                    kept_existing_clip = True

                deduplicated_clips.append(clip)

            if len(deduplicated_clips) != len(clips) or (
                matching_clips[0].get("clip_path") != clip_path
                or matching_clips[0].get("notes") != notes
            ):
                self._write(deduplicated_clips)

            return existing_clip

        # Ignore invalid legacy IDs and booleans (bool is a subclass of int).
        # New IDs are always positive integers greater than existing valid IDs.
        next_id = max(
            (
                clip["id"]
                for clip in clips
                if isinstance(clip, dict)
                and isinstance(clip.get("id"), int)
                and not isinstance(clip.get("id"), bool)
                and clip["id"] > 0
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
