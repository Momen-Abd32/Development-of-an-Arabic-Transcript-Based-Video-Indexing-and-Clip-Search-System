import pytest

from src.evaluation.metrics import EvaluationMetrics


def test_wer_perfect_match():
    result = EvaluationMetrics.calculate_wer(
        "مرحبا كيف حالك",
        "مرحبا كيف حالك",
    )
    assert result == 0.0


def test_wer_with_missing_word():
    result = EvaluationMetrics.calculate_wer(
        "مرحبا كيف حالك اليوم",
        "مرحبا كيف حالك",
    )
    assert result == 0.25


def test_cer_perfect_match():
    result = EvaluationMetrics.calculate_cer(
        "مرحبا كيف حالك",
        "مرحبا كيف حالك",
    )
    assert result == 0.0


def test_evaluate_returns_both_metrics():
    result = EvaluationMetrics.evaluate(
        "مرحبا كيف حالك",
        "مرحبا كيف حالك",
    )

    assert "wer" in result
    assert "cer" in result
    assert result["wer"] == 0.0
    assert result["cer"] == 0.0


def test_arabic_normalization():
    result = EvaluationMetrics.evaluate(
        "إِنَّ الْعَرَبِيَّةَ جَمِيلَة",
        "ان العربية جميلة",
    )

    assert result["wer"] == 0.0
    assert result["cer"] == 0.0


def test_empty_reference_raises_error():
    with pytest.raises(ValueError):
        EvaluationMetrics.calculate_wer("", "مرحبا")


def test_non_string_input_raises_error():
    with pytest.raises(TypeError):
        EvaluationMetrics.calculate_wer(123, "مرحبا")
