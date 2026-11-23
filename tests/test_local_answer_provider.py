import json

import pytest

import src.search.local_answer_provider as provider_module
from src.search.local_answer_provider import OllamaAnswerProvider


def test_ollama_provider_posts_question_and_bounded_evidence_to_loopback(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "message": {
                    "content": json.dumps({
                        "abstain": False,
                        "claims": [{
                            "text": "وصلت الشحنة إلى عمّان.",
                            "citations": [{"media_id": "media-1", "segment_id": 4}],
                        }],
                    }, ensure_ascii=False)
                }
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(provider_module, "urlopen", fake_urlopen)
    provider = OllamaAnswerProvider(model="qwen2.5:3b", timeout=45)
    result = provider.generate_answer(
        "إلى أين وصلت الشحنة؟",
        [{
            "media_id": "media-1",
            "segment_id": 4,
            "start": 10.0,
            "end": 12.0,
            "text": "وصلت الشحنة إلى عمّان.",
            "speaker": "SPEAKER_00",
        }],
    )

    assert result["claims"][0]["citations"][0]["segment_id"] == 4
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 45
    assert captured["payload"]["model"] == "qwen2.5:3b"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["format"] == "json"
    assert captured["payload"]["messages"][1]["content"].find("وصلت الشحنة") >= 0


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://192.168.1.10:11434",
        "http://127.0.0.1:8080",
        "http://user:pass@127.0.0.1:11434",
    ],
)
def test_ollama_provider_rejects_non_loopback_or_unexpected_endpoints(base_url):
    with pytest.raises(ValueError, match="local loopback"):
        OllamaAnswerProvider(base_url=base_url)


def test_ollama_provider_supports_ipv6_loopback():
    provider = OllamaAnswerProvider(base_url="http://[::1]:11434")
    assert provider.base_url == "http://[::1]:11434"


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan")])
def test_ollama_provider_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="Timeout"):
        OllamaAnswerProvider(timeout=timeout)


def test_ollama_provider_rejects_empty_model_name():
    with pytest.raises(ValueError, match="model name"):
        OllamaAnswerProvider(model=" ")
