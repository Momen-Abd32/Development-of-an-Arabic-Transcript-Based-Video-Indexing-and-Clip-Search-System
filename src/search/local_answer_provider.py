"""Optional local Ollama answer generation for evidence-grounded archive Q&A.

The adapter intentionally accepts loopback URLs only: transcript evidence must not
be sent to a remote host by this local-only integration.
"""
from __future__ import annotations

import json
import math
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class OllamaAnswerProvider:
    """Generate structured claims with references to retrieved transcript evidence."""

    def __init__(
        self,
        model: str = "qwen2.5:3b",
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
    ):
        if not isinstance(model, str) or not model.strip() or len(model) > 120:
            raise ValueError("Ollama model name must be a non-empty string.")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Timeout must be a positive finite number.")

        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port not in {None, 11434}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Ollama must use the local loopback service at http://127.0.0.1:11434."
            )

        self.model = model.strip()
        self.base_url = f"http://{parsed.hostname}:11434"
        self.timeout = float(timeout)

    def generate_answer(self, question: str, evidence: list[dict]) -> dict:
        """Return JSON claims; every claim is required to cite retrieved evidence."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Question must be a non-empty string.")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Evidence must be a non-empty list.")

        compact_evidence = []
        for item in evidence:
            compact_evidence.append({
                "media_id": item["media_id"],
                "segment_id": item["segment_id"],
                "start": item["start"],
                "end": item["end"],
                "speaker": item.get("speaker"),
                "text": item["text"][:4000],
            })

        system_prompt = (
            "You answer questions using ONLY the supplied Arabic transcript evidence. "
            "Do not use outside knowledge or infer missing facts. If the evidence does "
            "not directly support an answer, return {\"abstain\":true,\"claims\":[]} . "
            "Otherwise return JSON only with this shape: "
            "{\"abstain\":false,\"claims\":[{\"text\":\"one concise factual claim\","
            "\"citations\":[{\"media_id\":\"exact id\",\"segment_id\":1}]}]}. "
            "Every claim must cite one or more exact media_id/segment_id pairs from the "
            "evidence. Never invent IDs. Answer in the language of the question. "
            "Do not rewrite quoted transcript as if it were a verbatim quote."
        )
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"question": question, "evidence": compact_evidence},
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        request = Request(
            self.base_url + "/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
        message = response_data.get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Ollama returned no message content.")
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("Ollama answer must be a JSON object.")
        return result
