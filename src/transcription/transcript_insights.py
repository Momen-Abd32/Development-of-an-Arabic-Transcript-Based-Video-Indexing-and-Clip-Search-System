"""Extractive transcript summaries and keyword insights.

This module deliberately reuses verbatim transcript sentences. It does not
rewrite dialect, translate speech, or claim to generate abstractive summaries.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path


_TOKEN_PATTERN = re.compile(r"[\u0621-\u064A\u064B-\u065F\u0670]+|[A-Za-z][A-Za-z0-9]+")
_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_ARABIC_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"})
_STOPWORDS = {
    "في", "من", "على", "الى", "إلى", "عن", "مع", "هذا", "هذه", "ذلك",
    "تلك", "هو", "هي", "هم", "هن", "كان", "كانت", "يكون", "تكون",
    "ما", "ماذا", "متى", "أين", "كيف", "لم", "لن", "لا", "نعم",
    "و", "او", "أو", "ثم", "قد", "كل", "بعض", "بين", "بعد", "قبل",
    "the", "and", "for", "with", "from", "that", "this", "are", "was",
}
_STOPWORDS_NORMALIZED = {
    _ARABIC_DIACRITICS.sub("", word).translate(_ARABIC_ALEF).lower()
    for word in _STOPWORDS
}


class TranscriptInsights:
    """Generate reproducible extractive summaries and frequency keywords."""

    @staticmethod
    def _normalize_token(token: str) -> str:
        token = _ARABIC_DIACRITICS.sub("", token)
        return token.translate(_ARABIC_ALEF).lower()

    @classmethod
    def _tokens(cls, text: str) -> list[str]:
        return [
            normalized
            for token in _TOKEN_PATTERN.findall(text)
            if len(normalized := cls._normalize_token(token)) > 1
            and normalized not in _STOPWORDS_NORMALIZED
        ]

    @classmethod
    def generate(
        cls,
        segments: list[dict],
        keyword_limit: int = 10,
        summary_limit: int = 3,
    ) -> dict:
        if not isinstance(segments, list):
            raise TypeError("Segments must be a list.")
        if isinstance(keyword_limit, bool) or not isinstance(keyword_limit, int) or keyword_limit < 1:
            raise ValueError("Keyword limit must be a positive integer.")
        if isinstance(summary_limit, bool) or not isinstance(summary_limit, int) or summary_limit < 1:
            raise ValueError("Summary limit must be a positive integer.")

        valid_segments = []
        all_tokens = []
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
                raise ValueError(f"Segment {index} must contain transcript text.")
            start, end = segment.get("start"), segment.get("end")
            if (
                isinstance(start, bool) or not isinstance(start, (int, float))
                or isinstance(end, bool) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start
            ):
                raise ValueError(f"Segment {index} has invalid timestamps.")
            tokens = cls._tokens(segment["text"])
            valid_segments.append((index, segment, tokens))
            all_tokens.extend(tokens)

        counts = Counter(all_tokens)
        document_frequency = Counter()
        for _, _, tokens in valid_segments:
            document_frequency.update(set(tokens))
        term_weights = {
            term: frequency * (
                math.log((len(valid_segments) + 1) / (document_frequency[term] + 1))
                + 0.1
            )
            for term, frequency in counts.items()
        }
        keywords = [
            {
                "term": term,
                "frequency": frequency,
                "document_frequency": document_frequency[term],
                "score": round(term_weights[term], 6),
            }
            for term, frequency in sorted(
                counts.items(),
                key=lambda item: (-term_weights[item[0]], -item[1], item[0]),
            )[:keyword_limit]
        ]

        if not counts:
            selected = []
        else:
            scored = []
            for index, segment, tokens in valid_segments:
                if not tokens:
                    continue
                score = sum(term_weights[token] for token in tokens) / math.sqrt(len(tokens))
                scored.append((score, index, segment))
            selected = sorted(
                sorted(scored, key=lambda item: (-item[0], item[1]))[:summary_limit],
                key=lambda item: item[1],
            )

        topic_groups = {}
        for index, segment, tokens in valid_segments:
            if not tokens:
                continue
            local_counts = Counter(tokens)
            primary_term = max(
                local_counts,
                key=lambda term: (
                    local_counts[term] * term_weights[term],
                    term,
                ),
            )
            topic_groups.setdefault(primary_term, []).append(
                (index, segment, tokens)
            )

        topic_candidates = []
        for primary_term, members in topic_groups.items():
            topic_terms = Counter(
                token for _, _, tokens in members for token in tokens
            )
            topic_candidates.append({
                "label": primary_term,
                "keywords": [
                    term for term, _ in sorted(
                        topic_terms.items(),
                        key=lambda item: (-item[1], item[0]),
                    )[:5]
                ],
                "segment_count": len(members),
                "source_segments": [
                    {
                        "index": index,
                        "start": float(segment["start"]),
                        "end": float(segment["end"]),
                        "text": segment["text"],
                    }
                    for index, segment, _ in members
                ],
            })
        topic_candidates.sort(
            key=lambda topic: (-topic["segment_count"], topic["label"])
        )

        return {
            "method": "extractive",
            "normalization": "arabic_diacritics_and_alef_variants",
            "summary": " ".join(item[2]["text"].strip() for item in selected),
            "keywords": keywords,
            "topic_method": "segment_keyword_cooccurrence",
            "topic_candidates": topic_candidates[:5],
            "source_segments": [
                {
                    "index": index,
                    "start": float(segment["start"]),
                    "end": float(segment["end"]),
                    "text": segment["text"],
                }
                for _, index, segment in selected
            ],
        }

    @staticmethod
    def save(insights: dict, output_path: str | Path) -> Path:
        if not isinstance(insights, dict) or insights.get("method") != "extractive":
            raise ValueError("Only generated extractive insights can be saved.")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output.parent,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(insights, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, output)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return output

    @staticmethod
    def load(input_path: str | Path) -> dict:
        path = Path(input_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("method") != "extractive"
            or not isinstance(data.get("summary"), str)
            or not isinstance(data.get("keywords"), list)
            or not isinstance(data.get("source_segments"), list)
            or (
                "topic_candidates" in data
                and not isinstance(data["topic_candidates"], list)
            )
        ):
            raise ValueError("Invalid transcript insights file.")
        return data
