"""Provider protocols for the AI layer (F1).

Three capabilities, each behind a Protocol so implementations swap by config:
  - Embedder:  text -> vector           (memory embedding + semantic search)
  - ChatModel: grounded question -> answer  (agent chat sidebar)
  - Extractor: completed item -> lessons     (auto-extraction on done)

The default implementations (see stub.py) are deterministic and dependency-free,
so the whole stack runs offline. Ollama / OpenAI / Anthropic adapters are opt-in.
"""
from __future__ import annotations

import math
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class ChatModel(Protocol):
    def chat(self, *, system: str, context: str, question: str) -> str: ...


@runtime_checkable
class Extractor(Protocol):
    def extract(self, *, title: str, description: str) -> list[str]:
        """Return zero or more memory-shard texts distilled from a completed item."""
        ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
