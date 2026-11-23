"""Human-judged evaluation for fused transcript and keyframe rankings."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
import math


def _result_key(result: dict) -> tuple:
    result_type = result.get("result_type")
    media_id = result.get("media_id")
    if not isinstance(media_id, str) or not media_id.strip():
        raise ValueError("Cross-modal results require a non-empty media_id.")

    if result_type == "keyframe":
        frame_index = result.get("frame_index")
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index <= 0:
            raise ValueError("Keyframe relevance requires a positive frame_index.")
        return "keyframe", media_id, frame_index

    if result_type == "transcript":
        try:
            raw_start = result["start"]
            raw_end = result["end"]
            if isinstance(raw_start, bool) or isinstance(raw_end, bool):
                raise ValueError("Boolean timestamps are invalid.")
            start = float(raw_start)
            end = float(raw_end)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError("Transcript relevance requires numeric start and end timestamps.") from error
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError("Transcript relevance timestamps must satisfy finite 0 <= start < end.")
        return "transcript", media_id, round(start, 3), round(end, 3)

    raise ValueError("Cross-modal relevance result_type must be transcript or keyframe.")


def precision_at_k(ranked_results: Sequence[dict], relevant_results: Iterable[dict], k: int = 5) -> float:
    _validate_k(k)
    relevant = {_result_key(item) for item in relevant_results}
    if not relevant:
        return 0.0
    return sum(_result_key(item) in relevant for item in ranked_results[:k]) / k


def recall_at_k(ranked_results: Sequence[dict], relevant_results: Iterable[dict], k: int = 5) -> float:
    _validate_k(k)
    relevant = {_result_key(item) for item in relevant_results}
    if not relevant:
        return 0.0
    found = {
        _result_key(item)
        for item in ranked_results[:k]
        if _result_key(item) in relevant
    }
    return len(found) / len(relevant)


def reciprocal_rank(ranked_results: Sequence[dict], relevant_results: Iterable[dict]) -> float:
    relevant = {_result_key(item) for item in relevant_results}
    if not relevant:
        return 0.0
    for rank, result in enumerate(ranked_results, start=1):
        if _result_key(result) in relevant:
            return 1.0 / rank
    return 0.0


def evaluate_rankings(
    evaluations: Sequence[dict],
    rankings: Sequence[Sequence[dict]],
    k: int = 5,
) -> dict:
    _validate_k(k)
    if len(evaluations) != len(rankings):
        raise ValueError("Each cross-modal query must have exactly one ranking.")
    if not evaluations:
        raise ValueError("At least one cross-modal evaluation query is required.")

    per_query = []
    for case, ranking in zip(evaluations, rankings):
        relevant = case.get("relevant_results")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError("Every query needs a non-empty relevant_results list.")
        per_query.append({
            "query": case["query"],
            f"precision@{k}": precision_at_k(ranking, relevant, k),
            f"recall@{k}": recall_at_k(ranking, relevant, k),
            "reciprocal_rank": reciprocal_rank(ranking, relevant),
        })

    count = len(per_query)
    return {
        "query_count": count,
        f"precision@{k}": sum(item[f"precision@{k}"] for item in per_query) / count,
        f"recall@{k}": sum(item[f"recall@{k}"] for item in per_query) / count,
        "mrr": sum(item["reciprocal_rank"] for item in per_query) / count,
        "per_query": per_query,
    }


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer.")
