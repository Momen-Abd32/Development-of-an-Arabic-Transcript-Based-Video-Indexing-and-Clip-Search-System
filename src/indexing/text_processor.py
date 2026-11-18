
import re
import unicodedata


class ArabicTextProcessor:

    @staticmethod
    def normalize(text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("Input must be a string.")

        # Remove Arabic diacritics and Quranic marks
        text = re.sub(
            r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]',
            '',
            text,
        )

        # Normalize Alef variations
        text = re.sub(r'[إأآٱ]', 'ا', text)

        # Remove Tatweel
        text = text.replace('ـ', '')

        # Remove punctuation and symbols
        text = ''.join(
            char for char in text
            if unicodedata.category(char)[0] not in ('P', 'S')
        )

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    @staticmethod
    def tokenize(text: str) -> list[str]:
        normalized = ArabicTextProcessor.normalize(text)
        return normalized.split()
