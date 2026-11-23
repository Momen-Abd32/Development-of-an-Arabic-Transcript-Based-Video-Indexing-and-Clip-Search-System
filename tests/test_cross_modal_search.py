import pytest

from src.search.cross_modal_search import CrossModalSearch
from src.search.keyframe_search import KeyframeSearchIndex
from src.search.search_engine import SearchEngine


class FakeVisualProvider:
    model_name = "fake-cross-modal-v1"

    def embed_text(self, text):
        return [1.0, 0.0] if "سيارة" in text else [0.0, 1.0]

    def embed_images(self, image_paths):
        return [[1.0, 0.0] if "car" in path.name else [0.0, 1.0] for path in image_paths]


@pytest.fixture
def cross_modal(tmp_path):
    engine = SearchEngine(str(tmp_path / "transcripts.db"))
    engine.db.connection.executemany(
        """
        INSERT INTO segments (
            video_id, start, end, original_text, normalized_text, speaker
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("video-a", 10, 14, "سيارة حمراء في الشارع", "سيارة حمراء في الشارع", "SPEAKER_00"),
            ("video-b", 20, 24, "مشهد البحر والسفن", "مشهد البحر والسفن", None),
        ],
    )
    engine.db.connection.commit()

    visual = KeyframeSearchIndex(tmp_path / "visual.db")
    frame_a = tmp_path / "car-frame.jpg"
    frame_b = tmp_path / "sea-frame.jpg"
    frame_a.write_bytes(b"car frame")
    frame_b.write_bytes(b"sea frame")
    visual.replace_media_keyframes("video-a", [(frame_a, 12.0)])
    visual.replace_media_keyframes("video-b", [(frame_b, 22.0)])
    provider = FakeVisualProvider()
    visual.index_media("video-a", provider)
    visual.index_media("video-b", provider)

    yield CrossModalSearch(engine, visual), provider
    visual.close()
    engine.close()


def test_text_search_fuses_transcript_and_keyframe_results(cross_modal):
    search, provider = cross_modal
    results = search.search_text("سيارة حمراء", visual_provider=provider)

    assert {item["result_type"] for item in results} == {"transcript", "keyframe"}
    transcript = next(item for item in results if item["result_type"] == "transcript")
    assert {"exact", "fuzzy"}.issubset(set(transcript["matched_by"]))
    keyframe = next(item for item in results if item["result_type"] == "keyframe")
    assert transcript["cross_modal_score"] > keyframe["cross_modal_score"]
    assert keyframe["timestamp_seconds"] == 12.0
    assert keyframe["media_id"] == "video-a"
    assert keyframe["cross_modal_score"] > 0


def test_text_search_works_without_optional_visual_provider(cross_modal):
    search, _ = cross_modal
    results = search.search_text("سيارة حمراء", include_visual=False)

    assert results
    assert all(item["result_type"] == "transcript" for item in results)


def test_text_search_applies_media_and_speaker_filters(cross_modal):
    search, provider = cross_modal
    results = search.search_text(
        "سيارة",
        media_ids=["video-a"],
        speaker="SPEAKER_00",
        visual_provider=provider,
    )

    assert results
    assert {item["media_id"] for item in results} == {"video-a"}
    assert all(
        item["result_type"] == "keyframe" or item.get("speaker") == "SPEAKER_00"
        for item in results
    )


def test_text_search_empty_media_scope_returns_no_results(cross_modal):
    search, provider = cross_modal
    assert search.search_text("سيارة", media_ids=[], visual_provider=provider) == []


def test_image_search_returns_timestamped_visual_results(cross_modal, tmp_path):
    search, provider = cross_modal
    reference = tmp_path / "car-reference.jpg"
    reference.write_bytes(b"car reference")

    results = search.search_image(reference, provider, media_ids=["video-a"])

    assert len(results) == 1
    assert results[0]["result_type"] == "keyframe"
    assert results[0]["timestamp_seconds"] == 12.0
    assert results[0]["matched_by"] == ["visual"]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_cross_modal_search_rejects_invalid_limit(cross_modal, limit):
    search, provider = cross_modal
    with pytest.raises(ValueError):
        search.search_text("سيارة", limit=limit, visual_provider=provider)
