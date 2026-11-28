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



def test_collect_rankings_supports_standalone_semantic_mode():
    from scripts.evaluate_search import collect_rankings

    class FakeEngine:
        def semantic_search(self, query, provider, limit):
            return [{"query": query, "limit": limit, "provider": provider}]

    provider = object()
    cases = [{"query": "البحث الدلالي"}]
    results = collect_rankings(FakeEngine(), cases, "semantic", 7, provider)

    assert results[0][0]["query"] == "البحث الدلالي"
    assert results[0][0]["limit"] == 7
    assert results[0][0]["provider"] is provider


def test_collect_rankings_requires_provider_for_semantic_mode():
    from scripts.evaluate_search import collect_rankings

    with pytest.raises(ValueError, match="provider"):
        collect_rankings(object(), [{"query": "بحث"}], "semantic", 5)



def test_evaluate_modes_compares_all_rankers_on_the_same_judgments():
    from scripts.evaluate_search import evaluate_modes

    relevant = {"media_id": "media-a", "start": 1.0, "end": 2.0}

    class FakeEngine:
        def exact_search(self, query, limit):
            return [{"video_id": "media-a", "start": 1.0, "end": 2.0}]

        def fuzzy_search(self, query, limit):
            return [{"video_id": "media-a", "start": 1.0, "end": 2.0}]

        def semantic_search(self, query, provider, limit):
            return [{"video_id": "media-a", "start": 1.0, "end": 2.0}]

        def hybrid_search(self, query, provider, limit):
            return [{"video_id": "media-a", "start": 1.0, "end": 2.0}]

    cases = [{"query": "اختبار عربي", "relevant_segments": [relevant]}]
    reports = evaluate_modes(
        FakeEngine(), cases, ("exact", "fuzzy", "semantic", "hybrid"), 5,
        provider=object(),
    )

    assert set(reports) == {"exact", "fuzzy", "semantic", "hybrid"}
    assert all(report["query_count"] == 1 for report in reports.values())
    assert all(report["precision@5"] == 0.2 for report in reports.values())
    assert all(report["recall@5"] == 1.0 for report in reports.values())
    assert all(report["mrr"] == 1.0 for report in reports.values())


@pytest.mark.parametrize(
    "relevant",
    [
        {"media_id": "media-a", "start": -1, "end": 2},
        {"media_id": "media-a", "start": 3, "end": 2},
        {"media_id": "media-a", "start": 1, "end": 1},
        {"media_id": "media-a", "start": float("nan"), "end": 2},
        {"media_id": "media-a", "start": 0, "end": float("inf")},
        {"media_id": "", "start": 0, "end": 1},
        {"media_id": "media-a", "start": 0},
    ],
)
def test_load_dataset_rejects_invalid_relevant_segment_details(tmp_path, relevant):
    path = tmp_path / "invalid-segment.json"
    path.write_text(
        json.dumps({"queries": [{"query": "بحث عربي", "relevant_segments": [relevant]}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="query 0, relevant segment 0"):
        load_dataset(path)
