"""Provider registry (F1). Selects Embedder / ChatModel / Extractor from config.

Defaults are all-stub (offline). Selection is cached per-process; call reset() in
tests if you change settings at runtime.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.providers.base import ChatModel, Embedder, Extractor, cosine_similarity
from app.providers.stub import StubChat, StubEmbedder, StubExtractor

__all__ = [
    "Embedder",
    "ChatModel",
    "Extractor",
    "cosine_similarity",
    "get_embedder",
    "get_chat_model",
    "get_extractor",
    "iter_reply",
    "reset",
]


def iter_reply(model: ChatModel, *, system: str, context: str, question: str):
    """Yield reply chunks. Uses the provider's native stream() when available."""
    streamer = getattr(model, "stream", None)
    if callable(streamer):
        yield from streamer(system=system, context=context, question=question)
    else:
        yield model.chat(system=system, context=context, question=question)


@lru_cache
def get_embedder() -> Embedder:
    p = settings.embed_provider
    if p == "ollama":
        from app.providers import ollama

        return ollama.embedder()
    if p == "openai":
        from app.providers import openai

        return openai.embedder()
    return StubEmbedder()


@lru_cache
def get_chat_model() -> ChatModel:
    p = settings.chat_provider
    if p == "ollama":
        from app.providers import ollama

        return ollama.chat()
    if p == "anthropic":
        from app.providers import anthropic_provider

        return anthropic_provider.chat()
    return StubChat()


@lru_cache
def get_extractor() -> Extractor:
    p = settings.chat_provider
    if p == "ollama":
        from app.providers import ollama

        return ollama.extractor()
    if p == "anthropic":
        from app.providers import anthropic_provider

        return anthropic_provider.extractor()
    return StubExtractor()


def reset() -> None:
    get_embedder.cache_clear()
    get_chat_model.cache_clear()
    get_extractor.cache_clear()
