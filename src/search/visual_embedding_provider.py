"""Optional CLIP-compatible visual embedding provider."""
from __future__ import annotations

from pathlib import Path


class SentenceTransformerVisualProvider:
    """Use a shared CLIP text/image space through sentence-transformers."""

    def __init__(self, model_name: str = "clip-ViT-B-32-multilingual-v1"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "Visual search requires sentence-transformers. "
                "Install requirements-visual.txt first."
            ) from error
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    @staticmethod
    def _as_vectors(encoded):
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        if encoded and isinstance(encoded[0], (int, float)):
            return [encoded]
        return encoded

    def embed_text(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Visual text query cannot be empty.")
        encoded = self._model.encode([text], convert_to_numpy=True, normalize_embeddings=True)
        return self._as_vectors(encoded)[0]

    def embed_images(self, image_paths: list[Path]) -> list[list[float]]:
        if not isinstance(image_paths, list) or not image_paths:
            raise ValueError("At least one image path is required.")
        try:
            from PIL import Image
        except ImportError as error:
            raise RuntimeError("Pillow is required for visual search.") from error

        images = []
        try:
            for path in image_paths:
                with Image.open(path) as image:
                    images.append(image.convert("RGB"))
            encoded = self._model.encode(
                images,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return self._as_vectors(encoded)
        finally:
            for image in images:
                image.close()
