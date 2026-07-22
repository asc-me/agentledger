"""Local/self-hosted Ollama adapters (opt-in). Reachable at base_url — local,
over Tailscale, or a public endpoint guarded by a reverse proxy (Caddy) that wants a
bearer token (`auth_key`). Chat + embedding models are configured separately.
"""
from __future__ import annotations

import json

import httpx

from app.config import settings

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


def _headers(auth_key: str) -> dict:
    return {"Authorization": f"Bearer {auth_key}"} if auth_key else {}


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, dim: int, auth_key: str = ""):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_embed_model
        self.dim = dim
        self.auth_key = auth_key or ""

    def embed(self, text: str) -> list[float]:
        r = httpx.post(
            f"{self.base_url}/api/embeddings",
            headers=_headers(self.auth_key),
            json={"model": self.model, "prompt": text or ""},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["embedding"]


class OllamaChat:
    def __init__(self, base_url: str, model: str, auth_key: str = ""):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_chat_model
        self.auth_key = auth_key or ""

    def _msgs(self, system: str, context: str, question: str) -> list[dict]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Project context:\n{context}\n\nQuestion: {question}"},
        ]

    def chat(self, *, system: str, context: str, question: str) -> str:
        r = httpx.post(
            f"{self.base_url}/api/chat",
            headers=_headers(self.auth_key),
            json={"model": self.model, "messages": self._msgs(system, context, question), "stream": False},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()

    def stream(self, *, system: str, context: str, question: str):
        with httpx.stream(
            "POST",
            f"{self.base_url}/api/chat",
            headers=_headers(self.auth_key),
            json={"model": self.model, "messages": self._msgs(system, context, question), "stream": True},
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
    def __init__(self, base_url: str, model: str, auth_key: str = ""):
        self._chat = OllamaChat(base_url, model, auth_key)

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
    return OllamaEmbedder(
        settings.ollama_base_url, settings.ollama_embed_model, settings.embed_dim, settings.ollama_auth_key
    )


def chat(base_url: str = "", model: str = "", auth_key: str = "") -> OllamaChat:
    return OllamaChat(base_url, model, auth_key)


def extractor(base_url: str = "", model: str = "", auth_key: str = "") -> OllamaExtractor:
    return OllamaExtractor(base_url, model, auth_key)
