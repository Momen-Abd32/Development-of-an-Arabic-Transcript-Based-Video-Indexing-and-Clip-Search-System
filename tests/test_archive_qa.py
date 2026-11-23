import pytest

from src.search.archive_qa import ArchiveQA


class FakeSearchEngine:
    def __init__(self, exact=None, fuzzy=None, semantic=None):
        self.exact = exact or []
        self.fuzzy = fuzzy or []
        self.semantic = semantic or []
        self.calls = []

    def exact_search(self, query, **kwargs):
        self.calls.append(("exact", query, kwargs))
        return self.exact

    def fuzzy_search(self, query, **kwargs):
        self.calls.append(("fuzzy", query, kwargs))
        return self.fuzzy

    def semantic_search(self, query, provider, **kwargs):
        self.calls.append(("semantic", query, provider, kwargs))
        return self.semantic


def segment(segment_id, text, start=0.0, video_id="media-a", speaker=None):
    return {
        "id": segment_id,
        "video_id": video_id,
        "start": start,
        "end": start + 3.0,
        "original_text": text,
        "speaker": speaker,
    }


def test_archive_qa_returns_verbatim_quote_and_timestamped_citation():
    exact = [segment(4, "وصلت الشحنة إلى المستودع صباحاً.", start=12.5)]
    engine = FakeSearchEngine(exact=exact)
    result = ArchiveQA(engine).ask("متى وصلت الشحنة؟")

    assert result["status"] == "evidence_found"
    assert result["answer_type"] == "extractive_quote"
    assert result["answer"] == "وصلت الشحنة إلى المستودع صباحاً."
    assert result["answer_citation"] == {
        "media_id": "media-a",
        "segment_id": 4,
        "start": 12.5,
        "end": 15.5,
    }
    assert result["evidence"][0]["retrieved_by"] == ["exact"]


def test_archive_qa_fuses_retrievers_and_deduplicates_same_segment():
    shared = segment(2, "اجتمع الفريق في عمّان.", start=7)
    exact_only = segment(3, "تمت مناقشة الخطة.", start=14)
    engine = FakeSearchEngine(
        exact=[shared, exact_only],
        fuzzy=[shared],
    )

    result = ArchiveQA(engine).ask("أين اجتمع الفريق؟", limit=5)

    assert len(result["evidence"]) == 2
    assert result["evidence"][0]["segment_id"] == 2
    assert result["evidence"][0]["retrieved_by"] == ["exact", "fuzzy"]
    assert result["evidence"][0]["evidence_score"] > result["evidence"][1]["evidence_score"]


def test_archive_qa_passes_archive_scope_and_speaker_filter_to_retrievers():
    engine = FakeSearchEngine(exact=[segment(1, "قال المتحدث ذلك.", speaker="SPEAKER_00")])
    result = ArchiveQA(engine).ask(
        "ماذا قال المتحدث؟",
        media_ids=["media-a", "media-b"],
        speaker="SPEAKER_00",
    )

    assert result["status"] == "evidence_found"
    assert all(call[2]["media_ids"] == ["media-a", "media-b"] for call in engine.calls)
    assert all(call[2]["speaker"] == "SPEAKER_00" for call in engine.calls)


def test_archive_qa_can_include_optional_semantic_retrieval():
    provider = object()
    engine = FakeSearchEngine(
        semantic=[segment(9, "المؤتمر عُقد في عمّان.", start=21)]
    )

    result = ArchiveQA(engine).ask("أين عُقد المؤتمر؟", semantic_provider=provider)

    assert result["status"] == "evidence_found"
    assert result["evidence"][0]["retrieved_by"] == ["semantic"]
    assert engine.calls[-1][0] == "semantic"
    assert engine.calls[-1][2] is provider


def test_archive_qa_abstains_when_no_relevant_evidence_exists():
    engine = FakeSearchEngine()
    result = ArchiveQA(engine).ask("ما نتيجة الاجتماع؟")

    assert result == {
        "status": "insufficient_evidence",
        "answer_type": "abstention",
        "answer": None,
        "answer_citation": None,
        "evidence": [],
        "warnings": [],
        "message": (
            "No relevant transcript evidence was found in the selected archive scope. "
            "The system will not guess an answer."
        ),
    }


def test_archive_qa_returns_no_results_for_empty_archive_scope_without_search():
    engine = FakeSearchEngine()
    result = ArchiveQA(engine).ask("ما الموضوع؟", media_ids=[])

    assert result["status"] == "insufficient_evidence"
    assert engine.calls == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"question": ""},
        {"question": "سؤال", "limit": 0},
        {"question": "سؤال", "limit": True},
        {"question": "سؤال", "fuzzy_threshold": 101},
        {"question": "سؤال", "fuzzy_threshold": True},
        {"question": "سؤال", "rrf_k": 0},
        {"question": "سؤال", "rrf_k": True},
    ],
)
def test_archive_qa_validates_inputs(kwargs):
    question = kwargs.pop("question", "سؤال")
    with pytest.raises(ValueError):
        ArchiveQA(FakeSearchEngine()).ask(question, **kwargs)


def test_archive_qa_ignores_malformed_retrieval_rows_instead_of_citing_them():
    engine = FakeSearchEngine(
        exact=[{"id": "not-an-int", "video_id": "media-a", "start": 0, "end": 1,
                "original_text": "نص غير صالح"}]
    )

    result = ArchiveQA(engine).ask("سؤال")

    assert result["status"] == "insufficient_evidence"



def test_archive_qa_keeps_lexical_evidence_when_semantic_index_is_unavailable():
    class FailingSemanticEngine(FakeSearchEngine):
        def semantic_search(self, query, provider, **kwargs):
            raise RuntimeError("No semantic embeddings are available")

    engine = FailingSemanticEngine(exact=[segment(5, "انعقد الاجتماع يوم الأحد.")])
    result = ArchiveQA(engine).ask("متى انعقد الاجتماع؟", semantic_provider=object())

    assert result["status"] == "evidence_found"
    assert result["answer"] == "انعقد الاجتماع يوم الأحد."
    assert len(result["warnings"]) == 1
    assert "No semantic embeddings" in result["warnings"][0]



def test_archive_qa_integrates_with_sqlite_fts_and_fuzzy_retrieval(tmp_path):
    from src.search.search_engine import SearchEngine

    engine = SearchEngine(str(tmp_path / "archive_qa_integration.db"))
    try:
        engine.db.connection.execute(
            """
            INSERT INTO segments (
                video_id, start, end, original_text, normalized_text, speaker
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "archive-video-001",
                42.0,
                46.0,
                "أعلنت اللجنة نتائج الاجتماع صباح اليوم.",
                "اعلنت اللجنه نتائج الاجتماع صباح اليوم",
                "SPEAKER_01",
            ),
        )
        engine.db.connection.commit()

        result = ArchiveQA(engine).ask(
            "أعلنت اللجنة نتائج الاجتماع صباح اليوم",
            media_ids=["archive-video-001"],
        )

        assert result["status"] == "evidence_found"
        assert result["answer"] == "أعلنت اللجنة نتائج الاجتماع صباح اليوم."
        assert result["answer_citation"]["media_id"] == "archive-video-001"
        assert result["answer_citation"]["start"] == 42.0
        assert set(result["evidence"][0]["retrieved_by"]).issubset(
            {"exact", "fuzzy"}
        )
        assert result["evidence"][0]["retrieved_by"]
    finally:
        engine.close()



@pytest.mark.parametrize(
    "overrides",
    [
        {"start": float("nan")},
        {"end": float("inf")},
        {"start": -1.0},
        {"end": 0.0},
        {"original_text": ""},
    ],
)
def test_archive_qa_does_not_cite_invalid_transcript_evidence(overrides):
    invalid = segment(11, "محتوى", start=1.0)
    invalid.update(overrides)
    result = ArchiveQA(FakeSearchEngine(exact=[invalid])).ask("سؤال")

    assert result["status"] == "insufficient_evidence"
    assert result["evidence"] == []


class FakeAnswerProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def generate_answer(self, question, evidence):
        self.calls.append((question, evidence))
        if self.error:
            raise self.error
        return self.result


def test_archive_qa_accepts_generated_claims_only_with_retrieved_citations():
    engine = FakeSearchEngine(exact=[segment(12, "وصلت الشحنة إلى عمّان.", start=30)])
    provider = FakeAnswerProvider({
        "abstain": False,
        "claims": [{
            "text": "وصلت الشحنة إلى عمّان.",
            "citations": [{"media_id": "media-a", "segment_id": 12}],
        }],
    })

    result = ArchiveQA(engine).ask("إلى أين وصلت الشحنة؟", answer_provider=provider)

    assert result["answer_type"] == "cited_generated_claims"
    assert result["answer"] == "وصلت الشحنة إلى عمّان."
    assert result["answer_citations"] == [{
        "media_id": "media-a",
        "segment_id": 12,
        "start": 0.0,
        "end": 3.0,
    }]
    assert result["claims"][0]["citations"] == result["answer_citations"]
    assert provider.calls[0][0] == "إلى أين وصلت الشحنة؟"


@pytest.mark.parametrize(
    "generated",
    [
        {"abstain": False, "claims": [{"text": "إجابة مخترعة", "citations": [
            {"media_id": "not-in-archive", "segment_id": 999}
        ]}]},
        {"abstain": False, "claims": [{"text": "بلا مصدر", "citations": []}]},
        {"abstain": False, "claims": [{"text": "", "citations": [
            {"media_id": "media-a", "segment_id": 1}
        ]}]},
        {"abstain": True, "claims": []},
    ],
)
def test_archive_qa_falls_back_to_verbatim_evidence_for_invalid_or_abstaining_model(
    generated,
):
    engine = FakeSearchEngine(exact=[segment(1, "المعلومة المسجلة في التفريغ.", start=8)])
    provider = FakeAnswerProvider(generated)

    result = ArchiveQA(engine).ask("ما المعلومة؟", answer_provider=provider)

    assert result["answer_type"] == "extractive_quote"
    assert result["answer"] == "المعلومة المسجلة في التفريغ."
    assert result["answer_citations"][0]["segment_id"] == 1
    assert result["warnings"]


def test_archive_qa_falls_back_when_local_answer_provider_fails():
    engine = FakeSearchEngine(exact=[segment(7, "بدأ الاجتماع عند التاسعة.", start=9)])
    provider = FakeAnswerProvider(error=ConnectionError("Ollama is offline"))

    result = ArchiveQA(engine).ask("متى بدأ الاجتماع؟", answer_provider=provider)

    assert result["answer_type"] == "extractive_quote"
    assert result["answer"] == "بدأ الاجتماع عند التاسعة."
    assert "Ollama is offline" in result["warnings"][0]


def test_archive_qa_does_not_call_answer_provider_without_evidence():
    provider = FakeAnswerProvider({"abstain": False, "claims": []})

    result = ArchiveQA(FakeSearchEngine()).ask("سؤال", answer_provider=provider)

    assert result["status"] == "insufficient_evidence"
    assert provider.calls == []
