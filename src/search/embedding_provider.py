"""Optional multilingual sentence-embedding provider for semantic search.

The core application does not require this optional dependency. Install
sentence-transformers only when semantic search is enabled.
"""
from __future__ import annotations

from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    """Minimal interface implemented by embedding backends."""

    model_name: str

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        ...


class SentenceTransformerProvider:
    """Multilingual E5 provider; model loading is lazy and optional."""

    DEFAULT_MODEL = "intfloat/multilingual-e5-small"

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "Semantic search requires the optional 'sentence-transformers' "
                "package. Install it with: pip install sentence-transformers"
            ) from error

        self._model = SentenceTransformer(model_name)

    def embed_query(self, text: str) -> list[float]:
        vector = self._model.encode(
            f"query: {text}",
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vector.tolist()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            [f"passage: {text}" for text in texts],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]
