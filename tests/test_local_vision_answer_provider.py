import json

import pytest

import src.search.local_vision_answer_provider as provider_module
from src.search.local_vision_answer_provider import OllamaVisionAnswerProvider


def test_vision_provider_posts_local_frame_images_and_question(tmp_path, monkeypatch):
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fake-image")
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "message": {"content": json.dumps({
                    "abstain": False,
                    "answer": "تظهر مركبة.",
                    "citations": [{"media_id": "m1", "frame_index": 1}],
                }, ensure_ascii=False)}
            }).encode()

    class Opener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return Response()

    monkeypatch.setattr(provider_module, "build_opener", lambda *args: Opener())
    result = OllamaVisionAnswerProvider(timeout=15).generate_answer(
        "ماذا يظهر؟",
        [{
            "media_id": "m1",
            "frame_index": 1,
            "timestamp_seconds": 3.0,
            "image_path": str(image),
        }],
    )
    assert result["answer"] == "تظهر مركبة."
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == 15
    assert len(captured["payload"]["messages"][0]["images"]) == 1


@pytest.mark.parametrize(
    "base_url",
    ["https://127.0.0.1:11434", "http://localhost:11434", "http://example.com:11434"],
)
def test_vision_provider_rejects_non_loopback_urls(base_url):
    with pytest.raises(ValueError, match="loopback"):
        OllamaVisionAnswerProvider(base_url=base_url)


def test_vision_provider_rejects_oversized_and_unsupported_images(tmp_path):
    provider = OllamaVisionAnswerProvider()
    oversized = tmp_path / "large.jpg"
    oversized.write_bytes(b"x" * (provider.MAX_IMAGE_BYTES + 1))
    evidence = [{
        "media_id": "m1",
        "frame_index": 1,
        "timestamp_seconds": 0,
        "image_path": str(oversized),
    }]
    with pytest.raises(ValueError, match="5 MiB"):
        provider.generate_answer("سؤال", evidence)

    unsupported = tmp_path / "frame.gif"
    unsupported.write_bytes(b"gif")
    evidence[0]["image_path"] = str(unsupported)
    with pytest.raises(ValueError, match="supported image"):
        provider.generate_answer("سؤال", evidence)


def test_vision_provider_limits_frame_count(tmp_path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"image")
    evidence = [{
        "media_id": f"m{i}",
        "frame_index": i + 1,
        "timestamp_seconds": float(i),
        "image_path": str(image),
    } for i in range(5)]
    with pytest.raises(ValueError, match="At most 4"):
        OllamaVisionAnswerProvider().generate_answer("سؤال", evidence)
