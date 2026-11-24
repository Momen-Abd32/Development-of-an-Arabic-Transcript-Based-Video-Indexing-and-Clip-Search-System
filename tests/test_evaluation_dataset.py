import json

import pytest

from src.search.evaluation_dataset import EvaluationDatasetStore


def test_evaluation_dataset_starts_empty_and_saves_human_judgments(tmp_path):
    path = tmp_path / "evaluation" / "search_queries.json"
    store = EvaluationDatasetStore(path)

    initial = store.load()
    assert initial["queries"] == []

    saved = store.add_judgment(
        "اجتماع مجلس الإدارة",
        [{"media_id": "media-1", "start": 10, "end": 14}],
        notes="Reviewed against the source recording.",
    )

    assert path.is_file()
    assert saved["queries"] == [{
        "query": "اجتماع مجلس الإدارة",
        "relevant_segments": [{
            "media_id": "media-1",
            "start": 10.0,
            "end": 14.0,
        }],
        "notes": "Reviewed against the source recording.",
    }]
    assert store.load() == saved


def test_evaluation_dataset_merges_existing_query_and_deduplicates_timestamps(tmp_path):
    store = EvaluationDatasetStore(tmp_path / "search_queries.json")
    store.add_judgment(
        "موعد الاجتماع",
        [{"media_id": "media-1", "start": 10.0001, "end": 14.0001}],
    )

    result = store.add_judgment(
        "  موعد الاجتماع  ",
        [
            {"media_id": "media-1", "start": 10.0002, "end": 14.0002},
            {"media_id": "media-2", "start": 20, "end": 24},
        ],
    )

    assert len(result["queries"]) == 1
    assert len(result["queries"][0]["relevant_segments"]) == 2
    assert result["queries"][0]["relevant_segments"][0]["media_id"] == "media-1"
    assert result["queries"][0]["relevant_segments"][1]["media_id"] == "media-2"


@pytest.mark.parametrize(
    "query,segments",
    [
        ("", [{"media_id": "media-1", "start": 0, "end": 1}]),
        ("سؤال", []),
        ("سؤال", [{"media_id": "", "start": 0, "end": 1}]),
        ("سؤال", [{"media_id": "media-1", "start": -1, "end": 1}]),
        ("سؤال", [{"media_id": "media-1", "start": 1, "end": 1}]),
        ("سؤال", [{"media_id": "media-1", "start": float("nan"), "end": 2}]),
        ("سؤال", [{"media_id": "media-1", "start": 0, "end": float("inf")}]),
        ("سؤال", [{"media_id": "media-1", "start": 10**400, "end": 10**401}]),
        ("سؤال", [{"media_id": "media-1", "start": True, "end": 2}]),
    ],
)
def test_evaluation_dataset_rejects_invalid_judgments(tmp_path, query, segments):
    store = EvaluationDatasetStore(tmp_path / "search_queries.json")
    with pytest.raises((TypeError, ValueError)):
        store.add_judgment(query, segments)


def test_evaluation_dataset_rejects_malformed_existing_file(tmp_path):
    path = tmp_path / "search_queries.json"
    path.write_text(json.dumps({"queries": "invalid"}), encoding="utf-8")

    with pytest.raises(ValueError, match="queries list"):
        EvaluationDatasetStore(path).load()


def test_evaluation_dataset_does_not_overwrite_other_queries(tmp_path):
    store = EvaluationDatasetStore(tmp_path / "search_queries.json")
    store.add_judgment("سؤال أول", [{"media_id": "m1", "start": 0, "end": 2}])
    store.add_judgment("سؤال ثان", [{"media_id": "m2", "start": 5, "end": 8}])

    assert [item["query"] for item in store.load()["queries"]] == [
        "سؤال أول",
        "سؤال ثان",
    ]
