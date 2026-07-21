"""Offline, deterministic providers — the zero-dependency default.

These run with no external services and give stable, testable behavior.
"""
from __future__ import annotations

import hashlib
import math
import re

from app.config import settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_LESSON_MARKERS = ("decided", "learning", "convention", "must", "avoid", "fix", "fallback")


class StubEmbedder:
    """Hashed bag-of-tokens → L2-normalized vector. Same text → same vector."""

    def __init__(self, dim: int = settings.embed_dim):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _TOKEN_RE.findall((text or "").lower()):
            h = hashlib.sha256(tok.encode()).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            vec[idx] += 1.0 if h[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]


class StubChat:
    """Retrieval-grounded, no-LLM chat. Composes an answer from the given context."""

    def chat(self, *, system: str, context: str, question: str) -> str:
        lines = [context.strip()] if context.strip() else []
        lines.append(
            "(Local stub agent — no external model configured. "
            "Set CHAT_PROVIDER=ollama or anthropic for generative replies.)"
        )
        return "\n\n".join(lines)

    def stream(self, *, system: str, context: str, question: str):
        reply = self.chat(system=system, context=context, question=question)
        for i in range(0, len(reply), 24):  # emit in chunks to simulate token stream
            yield reply[i : i + 24]


class StubExtractor:
    """Heuristic lesson extraction: pull decision/learning-flavored sentences."""

    def extract(self, *, title: str, description: str) -> list[str]:
        sentences = [s.strip() for s in _SENT_RE.split(description or "") if s.strip()]
        hits = [s for s in sentences if any(m in s.lower() for m in _LESSON_MARKERS)]
        if hits:
            return hits[:3]
        # Fall back to a single completion note so `done` items always leave a trace.
        first = sentences[0] if sentences else ""
        note = f"Completed: {title}."
        if first:
            note += f" {first}"
        return [note]
