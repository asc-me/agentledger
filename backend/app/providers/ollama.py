"""Local Ollama adapters (opt-in). Requires an Ollama server reachable at base_url."""
from __future__ import annotations

import json

import httpx

from app.config import settings

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, dim: int):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        r = httpx.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text or ""},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["embedding"]


class OllamaChat:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(self, *, system: str, context: str, question: str) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Project context:\n{context}\n\nQuestion: {question}"},
        ]
        r = httpx.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": False},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()

    def stream(self, *, system: str, context: str, question: str):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Project context:\n{context}\n\nQuestion: {question}"},
        ]
        with httpx.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": True},
            timeout=_TIMEOUT,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                piece = obj.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if obj.get("done"):
                    break


class OllamaExtractor:
    def __init__(self, base_url: str, model: str):
        self._chat = OllamaChat(base_url, model)

    def extract(self, *, title: str, description: str) -> list[str]:
        system = (
            "You distill a completed dev task into 1-3 durable, reusable memory shards "
            "(decisions, learnings, conventions). Reply with one shard per line, no numbering."
        )
        out = self._chat.chat(
            system=system, context="", question=f"Task: {title}\n\nDetails: {description}"
        )
        return [ln.strip("-• ").strip() for ln in out.splitlines() if ln.strip()][:3]


def embedder() -> OllamaEmbedder:
    return OllamaEmbedder(settings.ollama_base_url, settings.ollama_embed_model, settings.embed_dim)


def chat() -> OllamaChat:
    return OllamaChat(settings.ollama_base_url, settings.ollama_chat_model)


def extractor() -> OllamaExtractor:
    return OllamaExtractor(settings.ollama_base_url, settings.ollama_chat_model)
