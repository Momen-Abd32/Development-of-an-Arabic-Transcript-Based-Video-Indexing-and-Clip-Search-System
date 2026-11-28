import pytest

from src.search.evaluation import (
    evaluate_rankings,
    precision_at_k,
    reciprocal_rank,
    recall_at_k,
)


def segment(media_id, start, end):
    return {"media_id": media_id, "start": start, "end": end}


def result(media_id, start, end):
    return {"video_id": media_id, "start": start, "end": end}


def test_precision_recall_and_reciprocal_rank():
    relevant = [segment("a", 0, 2), segment("b", 5, 7)]
    ranking = [
        result("x", 0, 1),
        result("b", 5, 7),
        result("a", 0, 2),
    ]
    assert precision_at_k(ranking, relevant, k=2) == 0.5
    assert recall_at_k(ranking, relevant, k=2) == 0.5
    assert reciprocal_rank(ranking, relevant) == 0.5


def test_metrics_use_media_and_timestamp_identity():
    relevant = [segment("media-a", 1.0001, 3.0001)]
    ranking = [result("media-a", 1.0, 3.0)]
    assert precision_at_k(ranking, relevant, k=1) == 1.0
    assert recall_at_k(ranking, relevant, k=1) == 1.0
    assert reciprocal_rank(ranking, relevant) == 1.0


def test_evaluate_rankings_returns_macro_averages():
    cases = [
        {"query": "الطقس", "relevant_segments": [segment("a", 0, 2)]},
        {"query": "الاقتصاد", "relevant_segments": [segment("b", 3, 5)]},
    ]
    rankings = [
        [result("a", 0, 2)],
        [result("x", 0, 2), result("b", 3, 5)],
    ]
    metrics = evaluate_rankings(cases, rankings, k=2)
    assert metrics["query_count"] == 2
    assert metrics["precision@2"] == 0.5
    assert metrics["recall@2"] == 1.0
    assert metrics["mrr"] == 0.75


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_metrics_reject_invalid_k(k):
    with pytest.raises(ValueError, match="positive integer"):
        precision_at_k([], [], k=k)


def test_evaluator_rejects_missing_relevance_judgments():
    with pytest.raises(ValueError, match="relevant_segments"):
        evaluate_rankings([{"query": "بدون أحكام"}], [[]])


def test_evaluator_requires_one_ranking_per_query():
    with pytest.raises(ValueError, match="exactly one ranking"):
        evaluate_rankings([{"query": "x", "relevant_segments": [segment("a", 0, 1)]}], [])


def test_transcript_metrics_reject_overflowing_timestamps():
    with pytest.raises(ValueError, match="Relevant segments"):
        precision_at_k(
            [],
            [segment("media-a", 10**400, 10**401)],
            k=1,
        )


@pytest.mark.parametrize(
    "relevant",
    [
        segment("a", float("nan"), 2),
        segment("a", 0, float("inf")),
        segment("a", -1, 2),
        segment("a", 2, 2),
        segment("a", 3, 2),
    ],
)
def test_metrics_reject_non_finite_or_invalid_timestamp_ranges(relevant):
    with pytest.raises(ValueError, match="timestamps"):
        precision_at_k([], [relevant], k=1)
