"""Anthropic (Claude) adapters for chat + extraction (opt-in cloud provider).

Uses the official `anthropic` SDK (optional dependency, imported lazily). Auth via
the standard ANTHROPIC_API_KEY env var. Model defaults to claude-opus-4-8.
"""
from __future__ import annotations

from app.config import settings

_MAX_TOKENS = 1024


def _client():
    import anthropic  # lazy: only needed when CHAT_PROVIDER=anthropic

    return anthropic.Anthropic()


def _text(message) -> str:
    return "".join(b.text for b in message.content if getattr(b, "type", None) == "text").strip()


class AnthropicChat:
    def __init__(self, model: str):
        self.model = model

    def chat(self, *, system: str, context: str, question: str) -> str:
        msg = _client().messages.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": f"Project context:\n{context}\n\nQuestion: {question}",
                }
            ],
        )
        return _text(msg)

    def stream(self, *, system: str, context: str, question: str):
        with _client().messages.stream(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[
                {"role": "user", "content": f"Project context:\n{context}\n\nQuestion: {question}"}
            ],
        ) as s:
            yield from s.text_stream


class AnthropicExtractor:
    def __init__(self, model: str):
        self.model = model

    def extract(self, *, title: str, description: str) -> list[str]:
        system = (
            "You distill a completed dev task into 1-3 durable, reusable memory shards "
            "(decisions, learnings, conventions). Reply with one shard per line, no numbering."
        )
        msg = _client().messages.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": f"Task: {title}\n\nDetails: {description}"}],
        )
        return [ln.strip("-• ").strip() for ln in _text(msg).splitlines() if ln.strip()][:3]


def chat() -> AnthropicChat:
    return AnthropicChat(settings.anthropic_model)


def extractor() -> AnthropicExtractor:
    return AnthropicExtractor(settings.anthropic_model)
