
import pytest

from src.indexing.text_processor import ArabicTextProcessor


def test_normalize_arabic_diacritics():
    result = ArabicTextProcessor.normalize("مَرْحَبًا بِكَ")
    assert result == "مرحبا بك"


def test_normalize_alef_variations():
    result = ArabicTextProcessor.normalize("أحمد إسلام آمال ٱدم")
    assert result == "احمد اسلام امال ادم"


def test_normalize_preserves_alef_maqsura():
    result = ArabicTextProcessor.normalize("على هدى")
    assert result == "على هدى"


def test_normalize_preserves_haa_and_taa_marbuta():
    result = ArabicTextProcessor.normalize("هبة هبه")
    assert result == "هبة هبه"


def test_normalize_distinguishes_yaa_and_alef_maqsura():
    result = ArabicTextProcessor.normalize("هدى هدي")
    assert result == "هدى هدي"


def test_normalize_removes_tatweel():
    result = ArabicTextProcessor.normalize("الـعـربـيـة")
    assert result == "العربية"


def test_normalize_removes_punctuation_and_symbols():
    result = ArabicTextProcessor.normalize("مرحبا، كيف حالك؟ #123!")
    assert result == "مرحبا كيف حالك 123"


def test_normalize_whitespace():
    result = ArabicTextProcessor.normalize("  مرحبا   كيف\nحالـك  ")
    assert result == "مرحبا كيف حالك"


def test_tokenize_arabic_text():
    result = ArabicTextProcessor.tokenize("مَرْحَبًا، كيف حالك؟")
    assert result == ["مرحبا", "كيف", "حالك"]


def test_non_string_input_raises_error():
    with pytest.raises(TypeError):
        ArabicTextProcessor.normalize(123)
