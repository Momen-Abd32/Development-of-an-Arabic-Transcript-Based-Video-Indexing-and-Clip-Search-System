import json

import pytest

from scripts.evaluate_search import load_dataset


def test_load_evaluation_dataset_accepts_human_relevance_labels(tmp_path):
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps({
            "queries": [{
                "query": "الأمن الغذائي",
                "relevant_segments": [{
                    "media_id": "a" * 64,
                    "start": 12.5,
                    "end": 16.0,
                }],
            }]
        }),
        encoding="utf-8",
    )
    cases = load_dataset(path)
    assert cases[0]["query"] == "الأمن الغذائي"
    assert cases[0]["relevant_segments"][0]["media_id"] == "a" * 64


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"queries": []},
        {"queries": [{"query": "   ", "relevant_segments": [{"media_id": "x", "start": 0, "end": 1}]}]},
        {"queries": [{"query": "بحث", "relevant_segments": []}]},
    ],
)
def test_load_evaluation_dataset_rejects_invalid_judgments(tmp_path, data):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_dataset(path)
