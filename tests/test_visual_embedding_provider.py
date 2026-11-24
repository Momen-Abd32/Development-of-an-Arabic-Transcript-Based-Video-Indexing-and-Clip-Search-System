import sys
import types

from src.search.visual_embedding_provider import SentenceTransformerVisualProvider


def test_visual_provider_uses_multilingual_text_encoder_and_original_clip_image_encoder(monkeypatch, tmp_path):
    calls = []

    class FakeModel:
        def __init__(self, name):
            self.name = name

        def encode(self, values, **kwargs):
            calls.append((self.name, values, kwargs))
            return [[1.0, 0.0] for _ in values]

    class FakeSentenceTransformer:
        def __new__(cls, name):
            return FakeModel(name)

    sentence_module = types.ModuleType("sentence_transformers")
    sentence_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_module)

    class FakeImage:
        def convert(self, mode):
            assert mode == "RGB"
            return self

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    image_api = types.SimpleNamespace(open=lambda path: FakeImage())
    pil_module = types.ModuleType("PIL")
    pil_module.Image = image_api
    pil_module.ImageOps = types.SimpleNamespace(exif_transpose=lambda image: image)
    monkeypatch.setitem(sys.modules, "PIL", pil_module)

    provider = SentenceTransformerVisualProvider()
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"fake-image")

    assert provider.model_name == "clip-ViT-B-32+clip-ViT-B-32-multilingual-v1"
    assert provider.embed_text("سيارة") == [1.0, 0.0]
    assert provider.embed_images([frame]) == [[1.0, 0.0]]
    assert [call[0] for call in calls] == [
        "clip-ViT-B-32-multilingual-v1",
        "clip-ViT-B-32",
    ]
