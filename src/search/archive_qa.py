"""Evidence-first question answering over indexed archive transcripts.

The initial answer is extractive: it quotes a retrieved transcript segment verbatim.
It does not invent a summary or claim that a passage proves more than it says.
"""
from __future__ import annotations


class ArchiveQA:
    """Retrieve timestamped transcript evidence and abstain when none is found."""

    def __init__(self, search_engine):
        self.search_engine = search_engine

    @staticmethod
    def _validate(question: str, limit: int, fuzzy_threshold: int, rrf_k: int) -> None:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Question must be a non-empty string.")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Limit must be a positive integer.")
        if (
            isinstance(fuzzy_threshold, bool)
            or not isinstance(fuzzy_threshold, (int, float))
            or not 0 <= fuzzy_threshold <= 100
        ):
            raise ValueError("Fuzzy threshold must be between 0 and 100.")
        if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k <= 0:
            raise ValueError("RRF k must be a positive integer.")

    def ask(
        self,
        question: str,
        *,
        media_ids: list[str] | None = None,
        speaker: str | None = None,
        limit: int = 5,
        fuzzy_threshold: int = 65,
        rrf_k: int = 60,
        semantic_provider=None,
    ) -> dict:
        """Return an extractive quote and ranked, citable transcript evidence."""
        self._validate(question, limit, fuzzy_threshold, rrf_k)
        if media_ids == []:
            return self._abstention()

        retrievals = [
            (
                "exact",
                self.search_engine.exact_search(
                    question, limit=limit * 4, media_ids=media_ids, speaker=speaker
                ),
            ),
            (
                "fuzzy",
                self.search_engine.fuzzy_search(
                    question,
                    threshold=fuzzy_threshold,
                    limit=limit * 4,
                    media_ids=media_ids,
                    speaker=speaker,
                ),
            ),
        ]
        if semantic_provider is not None:
            retrievals.append(
                (
                    "semantic",
                    self.search_engine.semantic_search(
                        question,
                        semantic_provider,
                        limit=limit * 4,
                        media_ids=media_ids,
                        speaker=speaker,
                    ),
                )
            )

        fused: dict[tuple[str, int], dict] = {}
        for source, results in retrievals:
            for rank, result in enumerate(results, start=1):
                video_id = result.get("video_id")
                segment_id = result.get("id")
                if not isinstance(video_id, str) or not video_id:
                    continue
                if isinstance(segment_id, bool) or not isinstance(segment_id, int):
                    continue
                key = (video_id, segment_id)
                item = fused.setdefault(key, dict(result))
                item["evidence_score"] = item.get("evidence_score", 0.0) + (
                    1.0 / (rrf_k + rank)
                )
                item.setdefault("retrieved_by", []).append(source)

        ranked = sorted(
            fused.values(),
            key=lambda item: (
                -item["evidence_score"],
                item["video_id"],
                float(item["start"]),
                item["id"],
            ),
        )[:limit]

        evidence = []
        for rank, item in enumerate(ranked, start=1):
            evidence.append(
                {
                    "rank": rank,
                    "media_id": item["video_id"],
                    "segment_id": item["id"],
                    "start": float(item["start"]),
                    "end": float(item["end"]),
                    "text": item["original_text"],
                    "speaker": item.get("speaker"),
                    "retrieved_by": item["retrieved_by"],
                    "evidence_score": item["evidence_score"],
                }
            )

        if not evidence:
            return self._abstention()

        return {
            "status": "evidence_found",
            "answer_type": "extractive_quote",
            "answer": evidence[0]["text"],
            "answer_citation": {
                "media_id": evidence[0]["media_id"],
                "segment_id": evidence[0]["segment_id"],
                "start": evidence[0]["start"],
                "end": evidence[0]["end"],
            },
            "evidence": evidence,
            "message": (
                "The answer is quoted verbatim from the highest-ranked transcript "
                "segment. Review the cited context before treating it as a complete answer."
            ),
        }

    @staticmethod
    def _abstention() -> dict:
        return {
            "status": "insufficient_evidence",
            "answer_type": "abstention",
            "answer": None,
            "answer_citation": None,
            "evidence": [],
            "message": (
                "No relevant transcript evidence was found in the selected archive scope. "
                "The system will not guess an answer."
            ),
        }
