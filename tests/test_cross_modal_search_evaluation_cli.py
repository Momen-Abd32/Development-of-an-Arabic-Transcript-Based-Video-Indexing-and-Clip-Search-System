import json

import pytest

from scripts.evaluate_cross_modal_search import load_dataset


def test_loader_accepts_mixed_relevance_judgments(tmp_path):
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps({
            "queries": [{
                "query": "سيارة حمراء",
                "relevant_results": [
                    {
                        "result_type": "transcript",
                        "media_id": "video-a",
                        "start": 1.0,
                        "end": 3.0,
                    },
                    {
                        "result_type": "keyframe",
                        "media_id": "video-a",
                        "frame_index": 2,
                    },
                ],
            }]
        }),
        encoding="utf-8",
    )

    cases = load_dataset(path)
    assert len(cases) == 1
    assert len(cases[0]["relevant_results"]) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"queries": []},
        {"queries": [{"query": "", "relevant_results": [{"result_type": "keyframe", "media_id": "a", "frame_index": 1}]}]},
        {"queries": [{"query": "سؤال", "relevant_results": []}]},
        {"queries": [{"query": "سؤال", "relevant_results": [{"result_type": "keyframe", "media_id": "a", "frame_index": 0}]}]},
    ],
)
def test_loader_rejects_invalid_cross_modal_datasets(tmp_path, payload):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_dataset(path)
