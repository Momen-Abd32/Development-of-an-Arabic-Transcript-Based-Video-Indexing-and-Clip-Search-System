
import csv
import pytest

from src.clips.clip_exporter import ClipExporter


def make_clip(**overrides):
    clip = {
        "id": 1,
        "video_id": "video1",
        "clip_path": "exports/clips/clip1.mp4",
        "start": 1.5,
        "end": 5.5,
        "duration": 4.0,
        "notes": "مقطع تجريبي",
        "created_at": "2026-11-17T10:00:00",
    }
    clip.update(overrides)
    return clip


def test_export_csv_success(tmp_path):
    output = tmp_path / "exports" / "clips.csv"

    result = ClipExporter.export_csv(
        [make_clip()],
        str(output),
    )

    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_export_csv_contains_correct_headers(tmp_path):
    output = tmp_path / "clips.csv"

    ClipExporter.export_csv([make_clip()], str(output))

    with output.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames == ClipExporter.FIELDS


def test_export_csv_preserves_arabic_text(tmp_path):
    output = tmp_path / "clips.csv"

    ClipExporter.export_csv([make_clip()], str(output))

    content = output.read_text(encoding="utf-8-sig")

    assert "مقطع تجريبي" in content


def test_export_csv_contains_all_rows(tmp_path):
    output = tmp_path / "clips.csv"

    clips = [
        make_clip(id=1),
        make_clip(id=2, video_id="video2"),
        make_clip(id=3, video_id="video3"),
    ]

    ClipExporter.export_csv(clips, str(output))

    with output.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 3
    assert rows[0]["id"] == "1"
    assert rows[1]["video_id"] == "video2"
    assert rows[2]["id"] == "3"


def test_export_csv_creates_parent_directory(tmp_path):
    output = tmp_path / "new" / "folder" / "clips.csv"

    ClipExporter.export_csv([make_clip()], str(output))

    assert output.exists()


def test_export_empty_list(tmp_path):
    output = tmp_path / "clips.csv"

    result = ClipExporter.export_csv([], str(output))

    assert result == output
    assert output.exists()

    with output.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert rows == []


def test_non_list_input_raises_error(tmp_path):
    with pytest.raises(TypeError, match="list"):
        ClipExporter.export_csv("invalid", str(tmp_path / "clips.csv"))


def test_non_dictionary_clip_raises_error(tmp_path):
    with pytest.raises(TypeError, match="dictionary"):
        ClipExporter.export_csv(
            ["invalid"],
            str(tmp_path / "clips.csv"),
        )


def test_missing_required_field_raises_error(tmp_path):
    clip = make_clip()
    del clip["video_id"]

    with pytest.raises(ValueError, match="missing fields"):
        ClipExporter.export_csv(
            [clip],
            str(tmp_path / "clips.csv"),
        )


def test_extra_fields_are_ignored(tmp_path):
    output = tmp_path / "clips.csv"

    clip = make_clip(extra_field="should not appear")

    ClipExporter.export_csv([clip], str(output))

    with output.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        row = next(reader)

    assert "extra_field" not in row
