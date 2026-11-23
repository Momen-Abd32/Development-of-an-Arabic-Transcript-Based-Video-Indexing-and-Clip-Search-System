import pytest

from src.search.visual_evaluation import (
    evaluate_rankings,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def frame(media_id, frame_index):
    return {"media_id": media_id, "frame_index": frame_index}


def test_visual_metrics_measure_top_k_relevance():
    relevant = [frame("video-a", 3), frame("video-b", 5)]
    ranking = [
        frame("video-x", 1),
        frame("video-b", 5),
        frame("video-a", 3),
    ]
    assert precision_at_k(ranking, relevant, k=2) == 0.5
    assert recall_at_k(ranking, relevant, k=2) == 0.5
    assert reciprocal_rank(ranking, relevant) == 0.5


def test_visual_metrics_distinguish_same_frame_index_in_different_videos():
    assert precision_at_k(
        [frame("video-a", 2)],
        [frame("video-b", 2)],
        k=1,
    ) == 0.0


def test_visual_evaluator_returns_macro_metrics():
    cases = [
        {"query": "سيارة حمراء", "relevant_frames": [frame("a", 1)]},
        {"query": "مذيع أمام الكاميرا", "relevant_frames": [frame("b", 2)]},
    ]
    rankings = [
        [frame("a", 1)],
        [frame("x", 1), frame("b", 2)],
    ]
    report = evaluate_rankings(cases, rankings, k=2)
    assert report["query_count"] == 2
    assert report["precision@2"] == 0.5
    assert report["recall@2"] == 1.0
    assert report["mrr"] == 0.75


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_visual_metrics_reject_invalid_k(k):
    with pytest.raises(ValueError, match="positive integer"):
        precision_at_k([], [], k)


@pytest.mark.parametrize(
    "item",
    [
        {"media_id": "", "frame_index": 1},
        {"media_id": "a", "frame_index": 0},
        {"media_id": "a", "frame_index": True},
    ],
)
def test_visual_metrics_reject_invalid_relevance_identity(item):
    with pytest.raises(ValueError):
        precision_at_k([item], [item], k=1)
