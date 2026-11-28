"""Evidence-first question answering over indexed archive transcripts.

The initial answer is extractive: it quotes a retrieved transcript segment verbatim.
It does not invent a summary or claim that a passage proves more than it says.
"""
from __future__ import annotations

import math


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
        answer_provider=None,
    ) -> dict:
        """Return an extractive quote and ranked, citable transcript evidence."""
        self._validate(question, limit, fuzzy_threshold, rrf_k)
        if media_ids == []:
            return self._abstention()

        warnings = []
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
            try:
                semantic_results = self.search_engine.semantic_search(
                    question,
                    semantic_provider,
                    limit=limit * 4,
                    media_ids=media_ids,
                    speaker=speaker,
                )
                retrievals.append(("semantic", semantic_results))
            except Exception as error:
                warnings.append(
                    "Semantic retrieval was unavailable; lexical evidence was still searched: "
                    + str(error)
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
                raw_start = result.get("start")
                raw_end = result.get("end")
                text = result.get("original_text")
                if isinstance(raw_start, bool) or isinstance(raw_end, bool):
                    continue
                try:
                    start = float(raw_start)
                    end = float(raw_end)
                except (TypeError, ValueError, OverflowError):
                    continue
                if (
                    not math.isfinite(start)
                    or not math.isfinite(end)
                    or start < 0
                    or end <= start
                    or not isinstance(text, str)
                    or not text.strip()
                ):
                    continue
                key = (video_id, segment_id)
                item = fused.setdefault(key, {
                    **result,
                    "start": start,
                    "end": end,
                })
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
            return self._abstention(warnings)

        answer_citation = {
            "media_id": evidence[0]["media_id"],
            "segment_id": evidence[0]["segment_id"],
            "start": evidence[0]["start"],
            "end": evidence[0]["end"],
        }
        answer_citations = [answer_citation]
        answer_type = "extractive_quote"
        answer = evidence[0]["text"]
        claims = []
        message = (
            "The answer is quoted verbatim from the highest-ranked transcript "
            "segment. Review the cited context before treating it as a complete answer."
        )

        if answer_provider is not None:
            try:
                generated = answer_provider.generate_answer(question, evidence)
                validated = self._validate_generated_claims(generated, evidence)
                if validated is not None:
                    claims, answer_citations = validated
                    answer = "\n".join(claim["text"] for claim in claims)
                    answer_type = "cited_generated_claims"
                    answer_citation = (
                        answer_citations[0] if len(answer_citations) == 1 else None
                    )
                    message = (
                        "Generated claims cite retrieved transcript segments. "
                        "Check the cited source context; citation validation confirms "
                        "source membership, not logical entailment."
                    )
                else:
                    warnings.append(
                        "The local answer model abstained or returned no valid cited claims; "
                        "the top transcript passage is shown instead."
                    )
            except Exception as error:
                warnings.append(
                    "Local answer generation was unavailable; the top transcript passage "
                    "is shown instead: " + str(error)
                )

        return {
            "status": "evidence_found",
            "answer_type": answer_type,
            "answer": answer,
            "answer_citation": answer_citation,
            "answer_citations": answer_citations,
            "claims": claims,
            "evidence": evidence,
            "warnings": warnings,
            "message": message,
        }

    @staticmethod
    def _claim_tokens(value: str) -> set[str]:
        """Normalize Arabic/Latin claim tokens for a conservative support check."""
        import re
        from src.indexing.text_processor import ArabicTextProcessor

        normalized = ArabicTextProcessor.normalize(value).casefold()
        tokens = set(re.findall(r"[\w]+", normalized, flags=re.UNICODE))
        stop_words = {
            "في", "من", "على", "الى", "إلى", "عن", "مع", "هذا", "هذه",
            "ذلك", "تلك", "هو", "هي", "كان", "كانت", "تم", "ثم", "و",
            "the", "a", "an", "is", "was", "were", "to", "of", "in", "on",
            "and", "or", "at", "by", "for", "with",
        }
        return {token for token in tokens if len(token) > 1 and token not in stop_words}

    @classmethod
    def _claim_has_lexical_support(cls, claim_text: str, cited_sources: list[dict]) -> bool:
        """Reject claims with weak lexical grounding or an obvious negation mismatch.

        This is a conservative heuristic guard, not a semantic entailment proof.
        """
        claim_tokens = cls._claim_tokens(claim_text)
        if not claim_tokens:
            return False
        evidence_tokens = set()
        evidence_text = " ".join(source.get("text", "") for source in cited_sources)
        for source in cited_sources:
            evidence_tokens.update(cls._claim_tokens(source.get("text", "")))
        overlap = claim_tokens & evidence_tokens
        required = 1 if len(claim_tokens) == 1 else 2
        if len(overlap) < required or len(overlap) / len(claim_tokens) < 0.5:
            return False

        negations = {"لا", "ليس", "لم", "لن", "ما", "غير", "بدون"}
        claim_negated = bool(claim_tokens & negations)
        evidence_negated = bool(cls._claim_tokens(evidence_text) & negations)
        if claim_negated != evidence_negated:
            return False
        return True

    @staticmethod
    def _validate_generated_claims(
        generated: dict,
        evidence: list[dict],
    ) -> tuple[list[dict], list[dict]] | None:
        """Accept only claims citing retrieved passages with conservative lexical support."""
        if not isinstance(generated, dict) or generated.get("abstain") is True:
            return None
        raw_claims = generated.get("claims")
        if not isinstance(raw_claims, list) or not raw_claims or len(raw_claims) > 8:
            return None

        available = {
            (item["media_id"], item["segment_id"]): item
            for item in evidence
        }
        claims = []
        all_citations = {}
        for raw_claim in raw_claims:
            if not isinstance(raw_claim, dict):
                return None
            text = raw_claim.get("text")
            raw_citations = raw_claim.get("citations")
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > 2000
                or not isinstance(raw_citations, list)
                or not raw_citations
                or len(raw_citations) > len(available)
            ):
                return None

            citations = []
            cited_sources = []
            seen = set()
            for raw_citation in raw_citations:
                if not isinstance(raw_citation, dict):
                    return None
                media_id = raw_citation.get("media_id")
                segment_id = raw_citation.get("segment_id")
                if (
                    not isinstance(media_id, str)
                    or isinstance(segment_id, bool)
                    or not isinstance(segment_id, int)
                ):
                    return None
                key = (media_id, segment_id)
                source = available.get(key)
                if source is None or key in seen:
                    return None
                seen.add(key)
                cited_sources.append(source)
                citation = {
                    "media_id": media_id,
                    "segment_id": segment_id,
                    "start": source["start"],
                    "end": source["end"],
                }
                citations.append(citation)
                all_citations[key] = citation
            if not ArchiveQA._claim_has_lexical_support(text.strip(), cited_sources):
                return None
            claims.append({"text": text.strip(), "citations": citations})

        return claims, list(all_citations.values())

    @staticmethod
    def _abstention(warnings: list[str] | None = None) -> dict:
        return {
            "status": "insufficient_evidence",
            "answer_type": "abstention",
            "answer": None,
            "answer_citation": None,
            "evidence": [],
            "warnings": warnings or [],
            "message": (
                "No relevant transcript evidence was found in the selected archive scope. "
                "The system will not guess an answer."
            ),
        }
