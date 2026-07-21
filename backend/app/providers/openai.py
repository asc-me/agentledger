"""OpenAI-compatible embeddings adapter (opt-in).

Anthropic has no embeddings endpoint, so cloud embeddings go through any
OpenAI-compatible `/v1/embeddings` API (OpenAI, or a self-hosted gateway).
"""
from __future__ import annotations

import httpx

from app.config import settings

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


class OpenAIEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, dim: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        r = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": text or ""},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]


def embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder(
        settings.openai_base_url, settings.openai_api_key, settings.openai_embed_model, settings.embed_dim
    )
