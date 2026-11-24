"""Persistent human relevance judgments for mixed transcript/keyframe retrieval."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from src.search.cross_modal_evaluation import _result_key


class CrossModalEvaluationDatasetStore:
    """Safely maintain a mixed-modality human evaluation dataset."""

    def __init__(
        self,
        path: str | Path = "data/evaluation/cross_modal_queries.json",
    ):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {
                "description": (
                    "Human-judged relevance labels for mixed transcript and keyframe retrieval."
                ),
                "queries": [],
            }
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
            raise ValueError("Cross-modal dataset must contain a queries list.")
        for index, case in enumerate(data["queries"]):
            if (
                not isinstance(case, dict)
                or not isinstance(case.get("query"), str)
                or not case["query"].strip()
                or not isinstance(case.get("relevant_results"), list)
                or not case["relevant_results"]
            ):
                raise ValueError(f"Invalid cross-modal query at index {index}.")
            for result in case["relevant_results"]:
                _result_key(result)
        return data

    def add_judgment(
        self,
        query: str,
        relevant_results: list[dict],
        notes: str | None = None,
    ) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Cross-modal query must be a non-empty string.")
        if not isinstance(relevant_results, list) or not relevant_results:
            raise ValueError("Select at least one relevant result.")
        if notes is not None and not isinstance(notes, str):
            raise TypeError("Evaluation notes must be a string or None.")

        validated = []
        for result in relevant_results:
            key = _result_key(result)
            if key[0] == "transcript":
                validated.append({
                    "result_type": "transcript",
                    "media_id": key[1],
                    "start": key[2],
                    "end": key[3],
                })
            else:
                validated.append({
                    "result_type": "keyframe",
                    "media_id": key[1],
                    "frame_index": key[2],
                })

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
                "relevant_results": [],
            }
            data["queries"].append(existing)

        merged = {
            _result_key(item): item
            for item in existing["relevant_results"]
        }
        for item in validated:
            merged[_result_key(item)] = item
        existing["relevant_results"] = list(merged.values())
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
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
