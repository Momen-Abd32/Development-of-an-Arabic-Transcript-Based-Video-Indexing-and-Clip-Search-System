"""Visual-only archive Q&A grounded in retrieved timestamped keyframes."""
from __future__ import annotations

import math


class VisualArchiveQA:
    """Retrieve relevant keyframes, then require a local vision model to cite frames."""

    def __init__(self, keyframe_index):
        self.keyframe_index = keyframe_index

    def ask(
        self,
        question: str,
        *,
        visual_provider,
        answer_provider,
        media_ids: list[str] | None = None,
        limit: int = 4,
    ) -> dict:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Question must be non-empty.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4:
            raise ValueError("Visual Q&A limit must be between 1 and 4.")
        if visual_provider is None or answer_provider is None:
            raise ValueError("Visual retrieval and a local vision answer provider are required.")
        if media_ids == []:
            return self._abstention("The selected archive scope is empty.")

        matches = self.keyframe_index.search_text(
            question.strip(),
            visual_provider,
            limit=limit,
            media_ids=media_ids,
        )
        evidence = []
        for item in matches:
            media_id = item.get("media_id")
            frame_index = item.get("frame_index")
            timestamp = item.get("timestamp_seconds")
            image_path = item.get("image_path")
            score = item.get("visual_score")
            if (
                not isinstance(media_id, str)
                or not media_id
                or isinstance(frame_index, bool)
                or not isinstance(frame_index, int)
                or frame_index < 1
                or isinstance(timestamp, bool)
                or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp)
                or timestamp < 0
                or not isinstance(image_path, str)
                or not image_path
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                continue
            evidence.append({
                "media_id": media_id,
                "frame_index": frame_index,
                "timestamp_seconds": float(timestamp),
                "image_path": image_path,
                "visual_score": float(score),
            })

        if not evidence:
            return self._abstention("No indexed visual evidence matched the question.")

        try:
            generated = answer_provider.generate_answer(question.strip(), evidence)
        except Exception as error:
            return self._abstention("Local vision answer generation failed: " + str(error))

        validated = self._validate_answer(generated, evidence)
        if validated is None:
            return self._abstention(
                "The vision model abstained or returned unsupported frame citations."
            )
        return {
            "status": "evidence_found",
            "answer_type": "cited_visual_answer",
            "answer": validated["answer"],
            "citations": validated["citations"],
            "evidence": evidence,
            "message": (
                "This answer is generated from retrieved keyframes only. "
                "Citations identify the source media and frame timestamp; "
                "they do not prove facts outside what is visible in those frames."
            ),
        }

    @staticmethod
    def _validate_answer(generated: dict, evidence: list[dict]) -> dict | None:
        if not isinstance(generated, dict) or generated.get("abstain") is True:
            return None
        answer = generated.get("answer")
        raw_citations = generated.get("citations")
        if (
            not isinstance(answer, str)
            or not answer.strip()
            or len(answer) > 2000
            or not isinstance(raw_citations, list)
            or not raw_citations
            or len(raw_citations) > len(evidence)
        ):
            return None
        available = {
            (item["media_id"], item["frame_index"]): item for item in evidence
        }
        citations = []
        seen = set()
        for raw in raw_citations:
            if not isinstance(raw, dict):
                return None
            media_id = raw.get("media_id")
            frame_index = raw.get("frame_index")
            if (
                not isinstance(media_id, str)
                or isinstance(frame_index, bool)
                or not isinstance(frame_index, int)
            ):
                return None
            key = (media_id, frame_index)
            item = available.get(key)
            if item is None or key in seen:
                return None
            seen.add(key)
            citations.append({
                "media_id": media_id,
                "frame_index": frame_index,
                "timestamp_seconds": item["timestamp_seconds"],
            })
        return {"answer": answer.strip(), "citations": citations}

    @staticmethod
    def _abstention(message: str) -> dict:
        return {
            "status": "insufficient_visual_evidence",
            "answer_type": "abstention",
            "answer": None,
            "citations": [],
            "evidence": [],
            "message": message,
        }
