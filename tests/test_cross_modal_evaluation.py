import pytest

from src.search.cross_modal_evaluation import (
    evaluate_rankings,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def transcript(media_id, start, end):
    return {
        "result_type": "transcript",
        "media_id": media_id,
        "start": start,
        "end": end,
    }


def keyframe(media_id, frame_index):
    return {
        "result_type": "keyframe",
        "media_id": media_id,
        "frame_index": frame_index,
    }


def test_metrics_evaluate_mixed_transcript_and_keyframe_results():
    relevant = [transcript("video-a", 10, 14), keyframe("video-b", 3)]
    ranking = [
        keyframe("video-x", 1),
        transcript("video-a", 10.0001, 14.0001),
        keyframe("video-b", 3),
    ]

    assert precision_at_k(ranking, relevant, k=2) == 0.5
    assert recall_at_k(ranking, relevant, k=2) == 0.5
    assert reciprocal_rank(ranking, relevant) == 0.5


def test_metrics_keep_transcript_and_keyframe_identities_separate():
    assert precision_at_k(
        [keyframe("video-a", 1)],
        [transcript("video-a", 0, 2)],
        k=1,
    ) == 0.0


def test_evaluator_returns_macro_metrics_for_mixed_queries():
    cases = [
        {
            "query": "سيارة حمراء",
            "relevant_results": [transcript("video-a", 10, 14)],
        },
        {
            "query": "مذيع أمام الكاميرا",
            "relevant_results": [keyframe("video-b", 2)],
        },
    ]
    rankings = [
        [transcript("video-a", 10, 14)],
        [keyframe("video-x", 1), keyframe("video-b", 2)],
    ]
    report = evaluate_rankings(cases, rankings, k=2)

    assert report["query_count"] == 2
    assert report["precision@2"] == 0.5
    assert report["recall@2"] == 1.0
    assert report["mrr"] == 0.75


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_cross_modal_metrics_reject_invalid_k(k):
    with pytest.raises(ValueError, match="positive integer"):
        precision_at_k([], [], k)


@pytest.mark.parametrize(
    "invalid",
    [
        {"result_type": "keyframe", "media_id": "a", "frame_index": 0},
        {"result_type": "transcript", "media_id": "a", "start": 4, "end": 4},
        {"result_type": "unknown", "media_id": "a"},
        {"result_type": "keyframe", "media_id": "", "frame_index": 1},
    ],
)
def test_cross_modal_metrics_reject_invalid_relevance_identity(invalid):
    with pytest.raises(ValueError):
        precision_at_k([invalid], [invalid], k=1)
