import json

import pytest

from src.transcription.transcript_insights import TranscriptInsights


def test_generates_extractive_summary_and_arabic_keywords():
    segments = [
        {"start": 0, "end": 2, "text": "الذكاء الاصطناعي يساعد في تحليل البيانات"},
        {"start": 2, "end": 4, "text": "تحليل البيانات يساعد المؤسسات"},
        {"start": 4, "end": 6, "text": "الرياضة مهمة للصحة"},
    ]

    result = TranscriptInsights.generate(segments, keyword_limit=3, summary_limit=2)

    assert result["method"] == "extractive"
    assert "الذكاء الاصطناعي" in result["summary"]
    assert len(result["source_segments"]) == 2
    assert result["keywords"][0]["term"] == "البيانات"
    assert result["source_segments"][0]["start"] == 0.0


def test_empty_transcript_returns_empty_insights():
    result = TranscriptInsights.generate([])

    assert result["summary"] == ""
    assert result["keywords"] == []
    assert result["source_segments"] == []


def test_ignores_stopwords_and_short_tokens():
    result = TranscriptInsights.generate([
        {"start": 0, "end": 1, "text": "في من على و لا"}
    ])

    assert result["keywords"] == []
    assert result["summary"] == ""


def test_rejects_invalid_segment_timestamps():
    with pytest.raises(ValueError, match="invalid timestamps"):
        TranscriptInsights.generate([
            {"start": 2, "end": 1, "text": "نص"}
        ])


def test_saves_and_loads_insights_atomically(tmp_path):
    insights = TranscriptInsights.generate([
        {"start": 0, "end": 2, "text": "أرشفة الوسائط والبحث"}
    ])
    output = tmp_path / "insights" / "media.json"

    TranscriptInsights.save(insights, output)

    assert TranscriptInsights.load(output) == insights
    assert json.loads(output.read_text(encoding="utf-8"))["method"] == "extractive"


def test_rejects_invalid_insights_file(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"summary": "text"}', encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid transcript insights"):
        TranscriptInsights.load(path)
