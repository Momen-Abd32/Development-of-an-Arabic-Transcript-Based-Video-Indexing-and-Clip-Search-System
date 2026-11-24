import pytest

from src.search.visual_archive_qa import VisualArchiveQA


class FakeKeyframeIndex:
    def __init__(self, matches):
        self.matches = matches
        self.calls = []

    def search_text(self, query, provider, **kwargs):
        self.calls.append((query, provider, kwargs))
        return self.matches


class FakeVisionProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def generate_answer(self, question, evidence):
        self.calls.append((question, evidence))
        if self.error:
            raise self.error
        return self.result


def frame(media="a" * 64, index=2, timestamp=18.5):
    return {
        "media_id": media,
        "frame_index": index,
        "timestamp_seconds": timestamp,
        "image_path": "/tmp/frame.jpg",
        "visual_score": 0.31,
    }


def test_visual_qa_returns_answer_with_exact_frame_timestamp_citations():
    index = FakeKeyframeIndex([frame()])
    answerer = FakeVisionProvider({
        "abstain": False,
        "answer": "تظهر شاحنة بيضاء أمام المستودع.",
        "citations": [{"media_id": "a" * 64, "frame_index": 2}],
    })

    result = VisualArchiveQA(index).ask(
        "ماذا يظهر أمام المستودع؟",
        visual_provider=object(),
        answer_provider=answerer,
    )

    assert result["status"] == "evidence_found"
    assert result["answer"] == "تظهر شاحنة بيضاء أمام المستودع."
    assert result["citations"] == [{
        "media_id": "a" * 64,
        "frame_index": 2,
        "timestamp_seconds": 18.5,
    }]
    assert answerer.calls[0][1][0]["image_path"] == "/tmp/frame.jpg"


@pytest.mark.parametrize(
    "generated",
    [
        {"abstain": True, "answer": "", "citations": []},
        {"abstain": False, "answer": "ادعاء بلا مصدر", "citations": []},
        {"abstain": False, "answer": "إجابة", "citations": [
            {"media_id": "not-in-archive", "frame_index": 2}
        ]},
        {"abstain": False, "answer": "", "citations": [
            {"media_id": "a" * 64, "frame_index": 2}
        ]},
    ],
)
def test_visual_qa_abstains_on_missing_or_invalid_citations(generated):
    result = VisualArchiveQA(FakeKeyframeIndex([frame()])).ask(
        "سؤال بصري",
        visual_provider=object(),
        answer_provider=FakeVisionProvider(generated),
    )
    assert result["status"] == "insufficient_visual_evidence"
    assert result["answer"] is None


def test_visual_qa_abstains_without_indexed_frames():
    answerer = FakeVisionProvider({"abstain": False, "answer": "x", "citations": []})
    result = VisualArchiveQA(FakeKeyframeIndex([])).ask(
        "سؤال",
        visual_provider=object(),
        answer_provider=answerer,
    )
    assert result["status"] == "insufficient_visual_evidence"
    assert answerer.calls == []


def test_visual_qa_passes_media_scope_to_keyframe_search():
    index = FakeKeyframeIndex([frame()])
    result = VisualArchiveQA(index).ask(
        "ما الموجود؟",
        visual_provider="clip",
        answer_provider=FakeVisionProvider({
            "abstain": False,
            "answer": "مركبة.",
            "citations": [{"media_id": "a" * 64, "frame_index": 2}],
        }),
        media_ids=["a" * 64],
    )
    assert result["status"] == "evidence_found"
    assert index.calls[0][2]["media_ids"] == ["a" * 64]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"question": ""},
        {"question": "سؤال", "limit": 0},
        {"question": "سؤال", "limit": 5},
        {"question": "سؤال", "limit": True},
    ],
)
def test_visual_qa_validates_arguments(kwargs):
    question = kwargs.pop("question", "سؤال")
    with pytest.raises(ValueError):
        VisualArchiveQA(FakeKeyframeIndex([])).ask(
            question,
            visual_provider=object(),
            answer_provider=object(),
            **kwargs,
        )


def test_visual_qa_abstains_when_vision_service_fails():
    result = VisualArchiveQA(FakeKeyframeIndex([frame()])).ask(
        "سؤال",
        visual_provider=object(),
        answer_provider=FakeVisionProvider(error=ConnectionError("offline")),
    )
    assert result["status"] == "insufficient_visual_evidence"
    assert "offline" in result["message"]
