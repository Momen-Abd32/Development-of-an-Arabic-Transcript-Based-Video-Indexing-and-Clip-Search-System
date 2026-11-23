import json

import pytest

from src.search.cross_modal_evaluation_dataset import CrossModalEvaluationDatasetStore


def test_cross_modal_dataset_saves_mixed_transcript_and_keyframe_judgments(tmp_path):
    path = tmp_path / "evaluation" / "cross_modal_queries.json"
    store = CrossModalEvaluationDatasetStore(path)

    result = store.add_judgment(
        "سيارة حمراء في الشارع",
        [
            {
                "result_type": "transcript",
                "media_id": "media-1",
                "start": 12.0,
                "end": 18.5,
            },
            {
                "result_type": "keyframe",
                "media_id": "media-1",
                "frame_index": 3,
            },
        ],
        notes="Both results reviewed against the original video.",
    )

    assert path.is_file()
    assert len(result["queries"][0]["relevant_results"]) == 2
    assert store.load() == result


def test_cross_modal_dataset_merges_and_deduplicates_relevance_labels(tmp_path):
    store = CrossModalEvaluationDatasetStore(tmp_path / "cross_modal_queries.json")
    store.add_judgment(
        "المشهد",
        [{
            "result_type": "transcript",
            "media_id": "media-1",
            "start": 1.0001,
            "end": 3.0001,
        }],
    )

    result = store.add_judgment(
        "المشهد",
        [
            {
                "result_type": "transcript",
                "media_id": "media-1",
                "start": 1.0002,
                "end": 3.0002,
            },
            {
                "result_type": "keyframe",
                "media_id": "media-2",
                "frame_index": 5,
            },
        ],
    )

    assert len(result["queries"]) == 1
    assert len(result["queries"][0]["relevant_results"]) == 2


@pytest.mark.parametrize(
    "result",
    [
        {"result_type": "transcript", "media_id": "", "start": 0, "end": 1},
        {"result_type": "transcript", "media_id": "m1", "start": -1, "end": 1},
        {"result_type": "transcript", "media_id": "m1", "start": 2, "end": 1},
        {"result_type": "transcript", "media_id": "m1", "start": True, "end": 2},
        {"result_type": "keyframe", "media_id": "m1", "frame_index": 0},
        {"result_type": "keyframe", "media_id": "m1", "frame_index": True},
        {"result_type": "image", "media_id": "m1", "frame_index": 1},
    ],
)
def test_cross_modal_dataset_rejects_invalid_results(tmp_path, result):
    store = CrossModalEvaluationDatasetStore(tmp_path / "cross_modal_queries.json")
    with pytest.raises(ValueError):
        store.add_judgment("سؤال", [result])


def test_cross_modal_dataset_rejects_malformed_existing_file(tmp_path):
    path = tmp_path / "cross_modal_queries.json"
    path.write_text(json.dumps({"queries": "invalid"}), encoding="utf-8")

    with pytest.raises(ValueError, match="queries list"):
        CrossModalEvaluationDatasetStore(path).load()
