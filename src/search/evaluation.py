"""Ranking metrics and relevance matching for transcript-search evaluation."""
from __future__ import annotations

from collections.abc import Iterable, Sequence


def _segment_key(segment: dict) -> tuple[str, float, float]:
    try:
        media_id = segment["video_id"] if "video_id" in segment else segment["media_id"]
        start = float(segment["start"])
        end = float(segment["end"])
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError(
            "Relevant segments require media_id/video_id, start, and end."
        ) from error
    if not isinstance(media_id, str) or not media_id.strip():
        raise ValueError("Relevant segment media ID cannot be empty.")
    return media_id, round(start, 3), round(end, 3)


def _result_key(result: dict) -> tuple[str, float, float]:
    return _segment_key(result)


def precision_at_k(ranked_results: Sequence[dict], relevant_segments: Iterable[dict], k: int = 5) -> float:
    """Return the fraction of the top-k results judged relevant (denominator k)."""
    _validate_k(k)
    relevant = {_segment_key(item) for item in relevant_segments}
    if not relevant:
        return 0.0
    hits = sum(
        _result_key(item) in relevant
        for item in ranked_results[:k]
    )
    return hits / k


def recall_at_k(ranked_results: Sequence[dict], relevant_segments: Iterable[dict], k: int = 5) -> float:
    """Return the fraction of all judged relevant segments found in the top k."""
    _validate_k(k)
    relevant = {_segment_key(item) for item in relevant_segments}
    if not relevant:
        return 0.0
    found = {
        _result_key(item)
        for item in ranked_results[:k]
        if _result_key(item) in relevant
    }
    return len(found) / len(relevant)


def reciprocal_rank(ranked_results: Sequence[dict], relevant_segments: Iterable[dict]) -> float:
    """Return reciprocal rank of the first relevant result."""
    relevant = {_segment_key(item) for item in relevant_segments}
    if not relevant:
        return 0.0
    for rank, item in enumerate(ranked_results, start=1):
        if _result_key(item) in relevant:
            return 1.0 / rank
    return 0.0


def evaluate_rankings(
    evaluations: Sequence[dict],
    rankings: Sequence[Sequence[dict]],
    k: int = 5,
) -> dict:
    """Compute macro-averaged P@k, R@k, and MRR for a set of query rankings."""
    _validate_k(k)
    if len(evaluations) != len(rankings):
        raise ValueError("Each evaluation query must have exactly one ranking.")
    if not evaluations:
        raise ValueError("At least one evaluation query is required.")

    per_query = []
    for case, ranking in zip(evaluations, rankings):
        relevant = case.get("relevant_segments")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError("Every query must contain a non-empty relevant_segments list.")
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
