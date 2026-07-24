"""OpenAI-compatible embeddings adapter (opt-in).

Anthropic has no embeddings endpoint, so cloud embeddings go through any
OpenAI-compatible `/v1/embeddings` API (OpenAI, or a self-hosted gateway such as an
Ollama instance exposing the compat surface, where the model is chosen by the
`model` field rather than a separate endpoint).
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger("agentledger.providers.openai")


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(settings.llm_timeout_seconds, connect=5.0)


class OpenAIEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, dim: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        """Embed one string, retrying transient failures.

        A cold model behind a gateway can take a while on the first call, and a blip
        shouldn't cost an ingest — so retry a bounded number of times with a short
        backoff before giving up. Callers that must not fail use `safe_embed`."""
        attempts = max(1, settings.embed_max_retries + 1)
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                r = httpx.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": text or ""},
                    timeout=_timeout(),
                )
                r.raise_for_status()
                return r.json()["data"][0]["embedding"]
            except Exception as e:  # noqa: BLE001 — retried, then re-raised below
                last = e
                if attempt + 1 < attempts:
                    logger.warning("embed attempt %d/%d failed: %s", attempt + 1, attempts, e)
                    time.sleep(0.5 * (attempt + 1))
        raise last  # type: ignore[misc]


def embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder(
        settings.openai_base_url, settings.openai_api_key, settings.openai_embed_model, settings.embed_dim
    )
