"""Persistent human relevance judgments for transcript retrieval evaluation."""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path


class EvaluationDatasetStore:
    """Safely maintain the human-labeled search evaluation dataset."""

    def __init__(self, path: str | Path = "data/evaluation/search_queries.json"):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {
                "description": (
                    "Human-judged relevance labels for Arabic transcript retrieval. "
                    "Only include segments reviewed by a person."
                ),
                "language_coverage": [
                    "Modern Standard Arabic",
                    "Arabic spelling variants",
                    "diacritics",
                    "mixed Arabic and English terms",
                ],
                "queries": [],
            }
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
            raise ValueError("Evaluation dataset must contain a queries list.")
        for index, case in enumerate(data["queries"]):
            if (
                not isinstance(case, dict)
                or not isinstance(case.get("query"), str)
                or not case["query"].strip()
                or not isinstance(case.get("relevant_segments"), list)
                or not case["relevant_segments"]
            ):
                raise ValueError(f"Invalid evaluation query at index {index}.")
            for segment in case["relevant_segments"]:
                self._validate_segment(segment)
        return data

    @staticmethod
    def _validate_segment(segment: dict) -> dict:
        if not isinstance(segment, dict):
            raise TypeError("A relevance judgment must be an object.")
        media_id = segment.get("media_id")
        start = segment.get("start")
        end = segment.get("end")
        if not isinstance(media_id, str) or not media_id.strip():
            raise ValueError("Relevant segment media_id must be a non-empty string.")
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
        ):
            raise TypeError("Relevant segment timestamps must be numbers.")
        try:
            start_value = float(start)
            end_value = float(end)
        except (OverflowError, ValueError) as error:
            raise ValueError("Relevant segment timestamps must be finite and valid.") from error
        if (
            not math.isfinite(start_value)
            or not math.isfinite(end_value)
            or start_value < 0
            or end_value <= start_value
        ):
            raise ValueError("Relevant segment timestamps must be finite and valid.")
        return {
            "media_id": media_id.strip(),
            "start": start_value,
            "end": end_value,
        }

    @staticmethod
    def _key(segment: dict) -> tuple[str, float, float]:
        return (
            segment["media_id"],
            round(segment["start"], 3),
            round(segment["end"], 3),
        )

    def add_judgment(
        self,
        query: str,
        relevant_segments: list[dict],
        notes: str | None = None,
    ) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Evaluation query must be a non-empty string.")
        if not isinstance(relevant_segments, list) or not relevant_segments:
            raise ValueError("Select at least one relevant segment.")
        if notes is not None and not isinstance(notes, str):
            raise TypeError("Evaluation notes must be a string or None.")

        validated = [self._validate_segment(item) for item in relevant_segments]
        data = self.load()
        existing = next(
            (
                item for item in data["queries"]
                if item["query"].strip().casefold() == query.strip().casefold()
            ),
            None,
        )
        if existing is None:
            existing = {
                "query": query.strip(),
                "relevant_segments": [],
            }
            data["queries"].append(existing)

        merged = {
            self._key(item): item
            for item in existing["relevant_segments"]
        }
        for item in validated:
            merged[self._key(item)] = item
        existing["relevant_segments"] = list(merged.values())
        if notes and notes.strip():
            existing["notes"] = notes.strip()

        self._write(data)
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(serialized)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
