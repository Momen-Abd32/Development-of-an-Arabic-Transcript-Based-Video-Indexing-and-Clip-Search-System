"""Optional speaker diarization for timestamped Arabic transcripts."""
from __future__ import annotations

import os
import math
from pathlib import Path
from typing import Iterable


def _valid_interval(start, end) -> bool:
    return (
        not isinstance(start, bool)
        and isinstance(start, (int, float))
        and not isinstance(end, bool)
        and isinstance(end, (int, float))
        and math.isfinite(start)
        and math.isfinite(end)
        and start >= 0
        and end > start
    )


def apply_speaker_turns(
    segments: list[dict],
    speaker_turns: Iterable[dict],
) -> list[dict]:
    """Attach the speaker with the greatest temporal overlap to each segment."""
    if not isinstance(segments, list):
        raise TypeError("Transcript segments must be a list.")
    turns = []
    for index, turn in enumerate(speaker_turns):
        if not isinstance(turn, dict) or not all(
            key in turn for key in ("start", "end", "speaker")
        ):
            raise ValueError(f"Speaker turn {index} is missing required fields.")
        start, end, speaker = turn["start"], turn["end"], turn["speaker"]
        if not _valid_interval(start, end) or not isinstance(speaker, str) or not speaker.strip():
            raise ValueError(f"Speaker turn {index} must have valid times and a speaker label.")
        turns.append((float(start), float(end), speaker.strip()))

    annotated = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or not all(
            key in segment for key in ("start", "end", "text")
        ):
            raise ValueError(f"Transcript segment {index} is missing required fields.")
        start, end = segment["start"], segment["end"]
        if not _valid_interval(start, end):
            raise ValueError(f"Transcript segment {index} must have valid timestamps.")
        if not isinstance(segment["text"], str):
            raise TypeError(f"Transcript segment {index} text must be a string.")
        start, end = float(start), float(end)

        overlap_by_speaker: dict[str, float] = {}
        for turn_start, turn_end, speaker in turns:
            overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
            if overlap:
                overlap_by_speaker[speaker] = (
                    overlap_by_speaker.get(speaker, 0.0) + overlap
                )

        updated = dict(segment)
        updated["speaker"] = (
            max(overlap_by_speaker, key=overlap_by_speaker.get)
            if overlap_by_speaker
            else "UNKNOWN"
        )
        annotated.append(updated)

    return annotated


class PyannoteSpeakerDiarizer:
    """Lazy pyannote adapter; requires a Hugging Face token and model access."""

    DEFAULT_MODEL = "pyannote/speaker-diarization-3.1"

    def __init__(self, model_name: str = DEFAULT_MODEL, token: str | None = None):
        self.model_name = model_name
        self.token = token or os.getenv("HF_TOKEN")
        if not self.token:
            raise RuntimeError(
                "Speaker diarization requires HF_TOKEN and access to the "
                "selected pyannote model on Hugging Face."
            )
        try:
            from pyannote.audio import Pipeline
        except ImportError as error:
            raise RuntimeError(
                "Speaker diarization requires the optional pyannote.audio package. "
                "Install requirements-diarization.txt."
            ) from error

        try:
            self.pipeline = Pipeline.from_pretrained(
                model_name,
                token=self.token,
            )
        except TypeError:
            # Compatibility with pyannote.audio releases using the older keyword.
            self.pipeline = Pipeline.from_pretrained(
                model_name,
                use_auth_token=self.token,
            )

    def diarize(self, audio_path: str) -> list[dict]:
        path = Path(audio_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("Audio file is missing or empty.")

        output = self.pipeline(str(path))
        annotation = getattr(output, "speaker_diarization", output)
        turns = []
        for segment, _, speaker in annotation.itertracks(yield_label=True):
            turns.append({
                "start": float(segment.start),
                "end": float(segment.end),
                "speaker": str(speaker),
            })
        return turns

    def annotate(self, segments: list[dict], audio_path: str) -> list[dict]:
        return apply_speaker_turns(segments, self.diarize(audio_path))
