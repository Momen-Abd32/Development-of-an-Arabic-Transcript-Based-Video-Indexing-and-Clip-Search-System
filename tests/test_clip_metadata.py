import json
import pytest

from src.clips.clip_metadata import ClipMetadata


def test_initializes_empty_metadata_file(tmp_path):
    path = tmp_path / "data" / "clips.json"

    manager = ClipMetadata(str(path))

    assert path.exists()
    assert manager.get_all_clips() == []


def test_save_clip_success(tmp_path):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    clip = manager.save_clip(
        "video1",
        "exports/clips/clip1.mp4",
        10,
        15,
        "مقطع تجريبي",
    )

    assert clip["id"] == 1
    assert clip["video_id"] == "video1"
    assert clip["clip_path"] == "exports/clips/clip1.mp4"
    assert clip["start"] == 10
    assert clip["end"] == 15
    assert clip["duration"] == 5
    assert clip["notes"] == "مقطع تجريبي"
    assert "created_at" in clip


def test_save_clip_preserves_arabic_text(tmp_path):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    manager.save_clip(
        "video1",
        "clip.mp4",
        0,
        5,
        "هذا مقطع باللغة العربية",
    )

    content = (tmp_path / "clips.json").read_text(encoding="utf-8")

    assert "هذا مقطع باللغة العربية" in content


def test_clip_ids_increment(tmp_path):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    first = manager.save_clip("video1", "one.mp4", 0, 2)
    second = manager.save_clip("video1", "two.mp4", 2, 4)

    assert first["id"] == 1
    assert second["id"] == 2


def test_saving_same_video_segment_does_not_duplicate_metadata(tmp_path):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    first = manager.save_clip("video1", "clip.mp4", 0, 2, "first save")
    repeated = manager.save_clip("video1", "clip.mp4", 0, 2, "second save")

    assert repeated == first
    assert len(manager.get_all_clips()) == 1
    assert repeated["notes"] == "first save"


def test_same_timestamps_in_different_videos_are_distinct(tmp_path):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    first = manager.save_clip("video1", "one.mp4", 0, 2)
    second = manager.save_clip("video2", "two.mp4", 0, 2)

    assert first["id"] == 1
    assert second["id"] == 2
    assert len(manager.get_all_clips()) == 2


def test_get_all_clips_returns_saved_clips(tmp_path):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    manager.save_clip("video1", "one.mp4", 0, 2)
    manager.save_clip("video2", "two.mp4", 3, 6)

    clips = manager.get_all_clips()

    assert len(clips) == 2
    assert clips[0]["video_id"] == "video1"
    assert clips[1]["video_id"] == "video2"


def test_metadata_persists_after_reopening(tmp_path):
    path = tmp_path / "clips.json"

    manager = ClipMetadata(str(path))
    manager.save_clip("video1", "clip.mp4", 1, 4, "test")

    reopened = ClipMetadata(str(path))

    assert len(reopened.get_all_clips()) == 1
    assert reopened.get_all_clips()[0]["notes"] == "test"


def test_invalid_json_raises_error(tmp_path):
    path = tmp_path / "clips.json"
    path.write_text("{invalid json", encoding="utf-8")

    manager = ClipMetadata(str(path))

    with pytest.raises(ValueError, match="invalid JSON"):
        manager.load()


def test_non_list_json_raises_error(tmp_path):
    path = tmp_path / "clips.json"
    path.write_text('{"clips": []}', encoding="utf-8")

    manager = ClipMetadata(str(path))

    with pytest.raises(ValueError, match="list"):
        manager.load()


@pytest.mark.parametrize(
    ("video_id", "clip_path"),
    [
        ("", "clip.mp4"),
        ("   ", "clip.mp4"),
        ("video1", ""),
        ("video1", "   "),
    ],
)
def test_empty_video_id_or_clip_path_raises_error(
    tmp_path, video_id, clip_path
):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    with pytest.raises(ValueError):
        manager.save_clip(video_id, clip_path, 0, 2)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (-1, 2),
        (3, 2),
        (2, 2),
    ],
)
def test_invalid_timestamps_raise_error(tmp_path, start, end):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    with pytest.raises(ValueError, match="timestamps"):
        manager.save_clip("video1", "clip.mp4", start, end)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (True, 2),
        (0, False),
        (float("nan"), 2),
        (0, float("inf")),
    ],
)
def test_non_finite_timestamps_raise_error(tmp_path, start, end):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    with pytest.raises(TypeError, match="finite numbers"):
        manager.save_clip("video1", "clip.mp4", start, end)


def test_non_string_notes_raise_error(tmp_path):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    with pytest.raises(TypeError, match="Notes"):
        manager.save_clip("video1", "clip.mp4", 0, 2, 123)


def test_empty_notes_are_allowed(tmp_path):
    manager = ClipMetadata(str(tmp_path / "clips.json"))

    clip = manager.save_clip("video1", "clip.mp4", 0, 2)

    assert clip["notes"] == ""
