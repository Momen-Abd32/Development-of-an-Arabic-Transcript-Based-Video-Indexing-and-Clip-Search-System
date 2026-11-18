from jiwer import wer, cer

from src.indexing.text_processor import ArabicTextProcessor


class EvaluationMetrics:

    @staticmethod
    def _normalize(text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("Evaluation text must be a string.")

        return ArabicTextProcessor.normalize(text)

    @staticmethod
    def calculate_wer(reference: str, hypothesis: str) -> float:
        reference = EvaluationMetrics._normalize(reference)
        hypothesis = EvaluationMetrics._normalize(hypothesis)

        if not reference:
            raise ValueError("Reference text cannot be empty.")

        return round(wer(reference, hypothesis), 4)

    @staticmethod
    def calculate_cer(reference: str, hypothesis: str) -> float:
        reference = EvaluationMetrics._normalize(reference)
        hypothesis = EvaluationMetrics._normalize(hypothesis)

        if not reference:
            raise ValueError("Reference text cannot be empty.")

        return round(cer(reference, hypothesis), 4)

    @staticmethod
    def evaluate(reference: str, hypothesis: str) -> dict:
        return {
            "wer": EvaluationMetrics.calculate_wer(
                reference, hypothesis
            ),
            "cer": EvaluationMetrics.calculate_cer(
                reference, hypothesis
            ),
        }
