"""Provider registry (F1). Selects Embedder / ChatModel / Extractor from config.

Defaults are all-stub (offline). Selection is cached per-process; call reset() in
tests if you change settings at runtime.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.providers.base import ChatModel, Embedder, Extractor, cosine_similarity
from app.providers.stub import StubChat, StubEmbedder, StubExtractor

from app.providers import registry

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
    "set_active_chat",
]


# Active chat/extraction provider, set by platform.apply_llm from the DB (or by the legacy
# env path). Kept as plain module state so a switch takes effect immediately.
_active: dict = {"provider": "stub", "base_url": "", "api_key": "", "model": ""}


def set_active_chat(provider: str = "stub", *, base_url: str = "", api_key: str = "", model: str = "") -> None:
    _active.update(
        provider=provider or "stub", base_url=base_url or "", api_key=api_key or "", model=model or ""
    )
    get_chat_model.cache_clear()
    get_extractor.cache_clear()


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


def _resolved_base_model(p: str) -> tuple[str, str]:
    meta = registry.get(p) or {}
    return (_active["base_url"] or meta.get("base_url", ""), _active["model"] or meta.get("chat_model", ""))


@lru_cache
def get_chat_model() -> ChatModel:
    p = _active["provider"]
    if p == "ollama":
        from app.providers import ollama

        return ollama.chat(base_url=_active["base_url"], model=_active["model"], auth_key=_active["api_key"])
    if p == "anthropic":
        from app.providers import anthropic_provider

        return anthropic_provider.chat(api_key=_active["api_key"], model=_active["model"])
    if registry.is_openai_compat(p):
        from app.providers import openai_compat

        base, model = _resolved_base_model(p)
        return openai_compat.chat(base, _active["api_key"], model)
    return StubChat()


@lru_cache
def get_extractor() -> Extractor:
    p = _active["provider"]
    if p == "ollama":
        from app.providers import ollama

        return ollama.extractor(base_url=_active["base_url"], model=_active["model"], auth_key=_active["api_key"])
    if p == "anthropic":
        from app.providers import anthropic_provider

        return anthropic_provider.extractor(api_key=_active["api_key"], model=_active["model"])
    if registry.is_openai_compat(p):
        from app.providers import openai_compat

        base, model = _resolved_base_model(p)
        return openai_compat.extractor(base, _active["api_key"], model)
    return StubExtractor()


def reset() -> None:
    get_embedder.cache_clear()
    get_chat_model.cache_clear()
    get_extractor.cache_clear()
