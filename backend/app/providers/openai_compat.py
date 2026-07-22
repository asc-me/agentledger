"""OpenAI-compatible chat adapter — one adapter for every provider that speaks the
OpenAI `/chat/completions` shape (OpenAI, Groq, DeepSeek, Mistral, xAI, Gemini's compat
endpoint). Parameterized by base_url + api_key + model; plain httpx, no SDK dependency.
"""
from __future__ import annotations

import json

import httpx

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


def _messages(system: str, context: str, question: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Project context:\n{context}\n\nQuestion: {question}"},
    ]


class OpenAICompatChat:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def chat(self, *, system: str, context: str, question: str) -> str:
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={"model": self.model, "messages": _messages(system, context, question)},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    def stream(self, *, system: str, context: str, question: str):
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={"model": self.model, "messages": _messages(system, context, question), "stream": True},
            timeout=_TIMEOUT,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta


class OpenAICompatExtractor:
    def __init__(self, base_url: str, api_key: str, model: str):
        self._chat = OpenAICompatChat(base_url, api_key, model)

    def extract(self, *, title: str, description: str) -> list[str]:
        system = (
            "You distill a completed dev task into 1-3 durable, reusable memory shards "
            "(decisions, learnings, conventions). Reply with one shard per line, no numbering."
        )
        out = self._chat.chat(system=system, context="", question=f"Task: {title}\n\nDetails: {description}")
        return [ln.strip("-• ").strip() for ln in out.splitlines() if ln.strip()][:3]


def chat(base_url: str, api_key: str, model: str) -> OpenAICompatChat:
    return OpenAICompatChat(base_url, api_key, model)


def extractor(base_url: str, api_key: str, model: str) -> OpenAICompatExtractor:
    return OpenAICompatExtractor(base_url, api_key, model)
