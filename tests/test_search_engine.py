import pytest

from src.search.search_engine import SearchEngine


@pytest.fixture
def search_engine(tmp_path):
    db_path = tmp_path / "test_search.db"
    engine = SearchEngine(str(db_path))

    engine.db.connection.executemany(
        """
        INSERT INTO segments (
            video_id,
            start,
            end,
            original_text,
            normalized_text
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("video1", 0, 2, "البرمجة جميلة", "البرمجة جميلة"),
            ("video1", 3, 5, "تعلم لغة بايثون", "تعلم لغة بايثون"),
            ("video2", 0, 2, "البرمجة ممتعة", "البرمجة ممتعة"),
            ("video2", 3, 5, "هبة مجتهدة", "هبة مجتهدة"),
            ("video2", 6, 8, "هدى ذكية", "هدى ذكية"),
        ],
    )

    engine.db.connection.execute(
        "UPDATE segments SET speaker = 'SPEAKER_00' WHERE id = 1"
    )
    engine.db.connection.commit()

    yield engine
    engine.close()


def test_exact_search_finds_matching_phrase(search_engine):
    results = search_engine.exact_search("البرمجة جميلة")

    assert len(results) == 1
    assert results[0]["original_text"] == "البرمجة جميلة"


def test_exact_search_filters_by_video(search_engine):
    results = search_engine.exact_search(
        "البرمجة",
        video_id="video2",
    )

    assert len(results) == 1
    assert results[0]["video_id"] == "video2"


def test_exact_search_empty_query_returns_empty(search_engine):
    assert search_engine.exact_search("   ") == []


def test_fuzzy_search_finds_similar_text(search_engine):
    results = search_engine.fuzzy_search(
        "البرمجة جميله",
        threshold=70,
    )

    assert len(results) >= 1
    assert results[0]["original_text"] == "البرمجة جميلة"


def test_fuzzy_search_orders_results_by_descending_similarity(search_engine):
    results = search_engine.fuzzy_search(
        "البرمجة جميله",
        threshold=0,
    )

    scores = [result["similarity"] for result in results]
    assert scores == sorted(scores, reverse=True)


def test_fuzzy_search_filters_by_video(search_engine):
    results = search_engine.fuzzy_search(
        "البرمجة",
        video_id="video2",
    )

    assert all(result["video_id"] == "video2" for result in results)


def test_fuzzy_search_empty_query_returns_empty(search_engine):
    assert search_engine.fuzzy_search("   ") == []


def test_search_distinguishes_taa_marbuta_and_haa(search_engine):
    taa_results = search_engine.exact_search("هبة")
    haa_results = search_engine.exact_search("هبه")

    assert len(taa_results) == 1
    assert len(haa_results) == 0


def test_search_distinguishes_alef_maqsura_and_yaa(search_engine):
    maqsura_results = search_engine.exact_search("هدى")
    yaa_results = search_engine.exact_search("هدي")

    assert len(maqsura_results) == 1
    assert len(yaa_results) == 0


def test_invalid_limit_is_rejected(search_engine):
    with pytest.raises(ValueError):
        search_engine.exact_search("البرمجة", limit=0)


def test_invalid_threshold_is_rejected(search_engine):
    with pytest.raises(ValueError):
        search_engine.fuzzy_search("البرمجة", threshold=101)

def test_fuzzy_search_respects_result_limit(search_engine):
    results = search_engine.fuzzy_search(
        "البرمجة",
        threshold=0,
        limit=1,
    )

    assert len(results) == 1


def test_boolean_search_limit_is_rejected(search_engine):
    with pytest.raises(ValueError):
        search_engine.exact_search("البرمجة", limit=True)

    with pytest.raises(ValueError):
        search_engine.fuzzy_search("البرمجة", limit=True)


class FakeEmbeddingProvider:
    model_name = "fake-arabic-v1"

    def embed_query(self, text):
        return [1.0, 0.0]

    def embed_documents(self, texts):
        return [
            [1.0, 0.0] if "البرمجة" in text else [0.0, 1.0]
            for text in texts
        ]


def test_semantic_search_uses_optional_embedding_index(search_engine):
    provider = FakeEmbeddingProvider()
    assert search_engine.index_semantic_media("video1", provider) == 2

    results = search_engine.semantic_search("البرمجة", provider)

    assert len(results) == 2
    assert all(result["video_id"] == "video1" for result in results)


def test_hybrid_search_combines_existing_and_semantic_search(search_engine):
    provider = FakeEmbeddingProvider()
    search_engine.index_semantic_media("video1", provider)

    results = search_engine.hybrid_search("البرمجة", provider)

    assert results
    assert all("hybrid_score" in result for result in results)
    assert any(result["video_id"] == "video1" for result in results)


def test_hybrid_search_requires_a_built_semantic_index(search_engine):
    with pytest.raises(RuntimeError, match="Build or refresh"):
        search_engine.hybrid_search(
            "البرمجة",
            FakeEmbeddingProvider(),
        )


def test_hybrid_search_validates_rrf_constant(search_engine):
    with pytest.raises(ValueError):
        search_engine.hybrid_search(
            "البرمجة",
            FakeEmbeddingProvider(),
            rrf_k=True,
        )


def test_boolean_fuzzy_threshold_is_rejected(search_engine):
    with pytest.raises(ValueError):
        search_engine.fuzzy_search("البرمجة", threshold=True)


def test_exact_search_filters_by_multiple_media_ids(search_engine):
    results = search_engine.exact_search(
        "البرمجة", media_ids=["video2"]
    )
    assert results
    assert {item["video_id"] for item in results} == {"video2"}


def test_exact_search_filters_by_speaker(search_engine):
    results = search_engine.exact_search(
        "البرمجة", speaker="SPEAKER_00"
    )
    assert len(results) == 1
    assert results[0]["video_id"] == "video1"


def test_search_filters_for_unassigned_speakers(search_engine):
    results = search_engine.exact_search(
        "البرمجة", speaker="__UNSPECIFIED_SPEAKER__"
    )
    assert len(results) == 1
    assert results[0]["video_id"] == "video2"


def test_fuzzy_search_applies_media_and_speaker_filters(search_engine):
    results = search_engine.fuzzy_search(
        "البرمجة", threshold=0, media_ids=["video1"], speaker="SPEAKER_00"
    )
    assert results
    assert all(item["video_id"] == "video1" for item in results)
    assert all(item["speaker"] == "SPEAKER_00" for item in results)


def test_empty_media_filter_returns_no_results(search_engine):
    assert search_engine.exact_search("البرمجة", media_ids=[]) == []
    assert search_engine.fuzzy_search("البرمجة", media_ids=[]) == []


def test_hybrid_search_applies_all_filters(search_engine):
    provider = FakeEmbeddingProvider()
    search_engine.index_semantic_media("video1", provider)
    search_engine.index_semantic_media("video2", provider)

    results = search_engine.hybrid_search(
        "البرمجة",
        provider,
        media_ids=["video1"],
        speaker="SPEAKER_00",
    )
    assert results
    assert all(item["video_id"] == "video1" for item in results)
    assert all(item["speaker"] == "SPEAKER_00" for item in results)


def test_hybrid_search_returns_empty_when_current_media_is_excluded(search_engine):
    assert search_engine.hybrid_search(
        "البرمجة",
        FakeEmbeddingProvider(),
        video_id="video1",
        media_ids=["video2"],
    ) == []
    assert search_engine.hybrid_search(
        "البرمجة",
        FakeEmbeddingProvider(),
        media_ids=[],
    ) == []


def test_list_speakers_returns_distinct_labels_in_archive_scope(search_engine):
    search_engine.db.connection.execute(
        "UPDATE segments SET speaker = 'SPEAKER_01' WHERE id IN (2, 3)"
    )
    search_engine.db.connection.commit()

    assert search_engine.list_speakers() == ["SPEAKER_00", "SPEAKER_01"]
    assert search_engine.list_speakers(media_ids=["video1"]) == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert search_engine.list_speakers(media_ids=["video2"]) == ["SPEAKER_01"]
    assert search_engine.list_speakers(media_ids=[]) == []
