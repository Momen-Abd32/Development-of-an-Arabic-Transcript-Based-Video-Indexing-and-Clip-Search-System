import json

import pytest

from scripts.evaluate_visual_search import load_dataset


def test_load_visual_evaluation_dataset_accepts_text_and_image_queries(tmp_path):
    path = tmp_path / "visual.json"
    path.write_text(
        json.dumps({
            "queries": [
                {
                    "query": "سيارة حمراء",
                    "relevant_frames": [{"media_id": "a" * 64, "frame_index": 3}],
                },
                {
                    "reference_image": "ref.jpg",
                    "relevant_frames": [{"media_id": "b" * 64, "frame_index": 4}],
                },
            ]
        }),
        encoding="utf-8",
    )
    cases = load_dataset(path)
    assert len(cases) == 2


@pytest.mark.parametrize(
    "case",
    [
        {"query": "", "reference_image": "", "relevant_frames": [{"media_id": "a", "frame_index": 1}]},
        {"query": "x", "reference_image": "ref.jpg", "relevant_frames": [{"media_id": "a", "frame_index": 1}]},
        {"query": "x", "relevant_frames": []},
    ],
)
def test_visual_dataset_rejects_invalid_queries(tmp_path, case):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"queries": [case]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_dataset(path)
