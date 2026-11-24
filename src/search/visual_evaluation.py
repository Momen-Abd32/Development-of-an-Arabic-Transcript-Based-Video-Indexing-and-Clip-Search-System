"""Ranking metrics for human-judged visual keyframe retrieval."""
from __future__ import annotations

from collections.abc import Iterable, Sequence


def _frame_key(frame: dict) -> tuple[str, int]:
    try:
        media_id = frame["media_id"]
        frame_index = frame["frame_index"]
    except (KeyError, TypeError) as error:
        raise ValueError("Relevant frames require media_id and frame_index.") from error
    if not isinstance(media_id, str) or not media_id.strip():
        raise ValueError("Relevant frame media ID cannot be empty.")
    if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index <= 0:
        raise ValueError("Relevant frame index must be a positive integer.")
    return media_id, frame_index


def precision_at_k(ranked_results: Sequence[dict], relevant_frames: Iterable[dict], k: int = 5) -> float:
    _validate_k(k)
    relevant = {_frame_key(item) for item in relevant_frames}
    if not relevant:
        return 0.0
    hits = sum(_frame_key(item) in relevant for item in ranked_results[:k])
    return hits / k


def recall_at_k(ranked_results: Sequence[dict], relevant_frames: Iterable[dict], k: int = 5) -> float:
    _validate_k(k)
    relevant = {_frame_key(item) for item in relevant_frames}
    if not relevant:
        return 0.0
    found = {
        _frame_key(item)
        for item in ranked_results[:k]
        if _frame_key(item) in relevant
    }
    return len(found) / len(relevant)


def reciprocal_rank(ranked_results: Sequence[dict], relevant_frames: Iterable[dict]) -> float:
    relevant = {_frame_key(item) for item in relevant_frames}
    if not relevant:
        return 0.0
    for rank, item in enumerate(ranked_results, start=1):
        if _frame_key(item) in relevant:
            return 1.0 / rank
    return 0.0


def evaluate_rankings(
    evaluations: Sequence[dict],
    rankings: Sequence[Sequence[dict]],
    k: int = 5,
) -> dict:
    _validate_k(k)
    if len(evaluations) != len(rankings):
        raise ValueError("Each visual query must have exactly one ranking.")
    if not evaluations:
        raise ValueError("At least one visual evaluation query is required.")

    per_query = []
    for case, ranking in zip(evaluations, rankings):
        relevant = case.get("relevant_frames")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError("Every visual query needs a non-empty relevant_frames list.")
        per_query.append({
            "query": case.get("query") or case.get("reference_image"),
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
