import pytest

from src.search.semantic_search import SemanticSearchIndex


class FakeEmbeddingProvider:
    model_name = "fake-arabic-v1"

    def embed_query(self, text):
        return [1.0, 0.0] if "برمجة" in text else [0.0, 1.0]

    def embed_documents(self, texts):
        return [
            [1.0, 0.0] if "برمجة" in text else [0.0, 1.0]
            for text in texts
        ]


@pytest.fixture
def semantic_index(tmp_path):
    database_path = tmp_path / "semantic.db"
    index = SemanticSearchIndex(str(database_path))
    index.connection.execute(
        """
        CREATE TABLE segments (
            id INTEGER PRIMARY KEY,
            video_id TEXT NOT NULL,
            start REAL NOT NULL,
            end REAL NOT NULL,
            original_text TEXT NOT NULL,
            normalized_text TEXT NOT NULL,
            speaker TEXT
        )
        """
    )
    index.connection.executemany(
        """
        INSERT INTO segments
            (id, video_id, start, end, original_text, normalized_text, speaker)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "media-a", 0, 2, "شرح البرمجة", "شرح البرمجة", "SPEAKER_00"),
            (2, "media-b", 4, 6, "أخبار اليوم", "اخبار اليوم", None),
            (3, "media-a", 7, 9, "تعلم البرمجة", "تعلم البرمجة", "SPEAKER_01"),
        ],
    )
    index.connection.commit()
    yield index
    index.close()


def test_indexes_and_searches_semantic_segments(semantic_index):
    provider = FakeEmbeddingProvider()
    assert semantic_index.index_media("media-a", provider) == 2

    results = semantic_index.search("برمجة", provider)

    assert [item["id"] for item in results] == [1, 3]
    assert results[0]["semantic_score"] == 1.0


def test_semantic_search_filters_by_media(semantic_index):
    provider = FakeEmbeddingProvider()
    semantic_index.index_media("media-a", provider)

    results = semantic_index.search("برمجة", provider, media_id="media-a")

    assert len(results) == 2
    assert all(item["video_id"] == "media-a" for item in results)


def test_reindex_replaces_previous_embeddings(semantic_index):
    provider = FakeEmbeddingProvider()
    semantic_index.index_media("media-a", provider)
    semantic_index.index_media("media-a", provider)

    count = semantic_index.connection.execute(
        "SELECT COUNT(*) FROM segment_embeddings"
    ).fetchone()[0]
    assert count == 2


def test_rejects_invalid_embeddings(semantic_index):
    class InvalidProvider(FakeEmbeddingProvider):
        def embed_documents(self, texts):
            return [[float("nan"), 0.0] for _ in texts]

    with pytest.raises(ValueError, match="finite"):
        semantic_index.index_media("media-a", InvalidProvider())


def test_rejects_wrong_embedding_dimensions(semantic_index):
    class WrongDimensionProvider(FakeEmbeddingProvider):
        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, text):
            return [1.0, 0.0, 0.0]

    provider = FakeEmbeddingProvider()
    semantic_index.index_media("media-a", provider)

    with pytest.raises(ValueError, match="dimensions"):
        semantic_index.search("برمجة", WrongDimensionProvider())

def test_rejects_inconsistent_dimensions_and_preserves_previous_index(semantic_index):
    provider = FakeEmbeddingProvider()
    semantic_index.index_media("media-a", provider)

    class InconsistentProvider(FakeEmbeddingProvider):
        def embed_documents(self, texts):
            return [[1.0, 0.0], [1.0, 0.0, 0.0]]

    with pytest.raises(ValueError, match="inconsistent vector dimensions"):
        semantic_index.index_media("media-a", InconsistentProvider())

    count = semantic_index.connection.execute(
        "SELECT COUNT(*) FROM segment_embeddings WHERE video_id = ?",
        ("media-a",),
    ).fetchone()[0]
    assert count == 2


def test_semantic_search_filters_by_media_ids_and_speaker(semantic_index):
    provider = FakeEmbeddingProvider()
    semantic_index.index_media("media-a", provider)
    results = semantic_index.search(
        "برمجة",
        provider,
        media_ids=["media-a"],
        speaker="SPEAKER_01",
    )
    assert [item["id"] for item in results] == [3]
    assert results[0]["speaker"] == "SPEAKER_01"


def test_semantic_search_filters_unassigned_speakers(semantic_index):
    provider = FakeEmbeddingProvider()
    semantic_index.index_media("media-b", provider)
    results = semantic_index.search(
        "أخبار",
        provider,
        speaker="__UNSPECIFIED_SPEAKER__",
    )
    assert [item["id"] for item in results] == [2]


def test_semantic_search_returns_exact_top_k_without_changing_tie_order(semantic_index):
    provider = FakeEmbeddingProvider()
    rows = [
        (
            index,
            f"media-{index % 7}",
            float(index),
            float(index + 1),
            "شرح البرمجة",
            "شرح البرمجة",
            None,
        )
        for index in range(100, 1300)
    ]
    semantic_index.connection.executemany(
        """
        INSERT INTO segments
            (id, video_id, start, end, original_text, normalized_text, speaker)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    semantic_index.connection.commit()
    semantic_index.index_media("media-0", provider)
    results = semantic_index.search("برمجة", provider, limit=5)

    assert [item["id"] for item in results] == [105, 112, 119, 126, 133]
    assert all(item["semantic_score"] == 1.0 for item in results)


def test_semantic_search_top_k_respects_media_and_speaker_filters(semantic_index):
    provider = FakeEmbeddingProvider()
    semantic_index.index_media("media-a", provider)
    semantic_index.index_media("media-b", provider)

    results = semantic_index.search(
        "برمجة",
        provider,
        limit=1,
        media_ids=["media-a"],
        speaker="SPEAKER_01",
    )

    assert [item["id"] for item in results] == [3]
