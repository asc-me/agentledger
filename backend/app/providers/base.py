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
from contextlib import contextmanager
from typing import Protocol, runtime_checkable

import httpx

from app import errors


@contextmanager
def provider_errors(provider: str, *, model: str = "", endpoint: str = ""):
    """Turn a provider transport failure into an ACTIONABLE domain error.

    Without this every provider problem reached the agent as
    `internal error executing 'grill_prd'` with the hint "safe to retry once" —
    which is worse than useless for a misconfiguration: retrying a refused
    connection never helps, and the hint sends the agent off to file a bug instead
    of checking Settings. That message cost two separate debugging sessions (a
    wrong model name, then a wrong base URL on a different project) before anyone
    saw the actual cause, which was one layer down the whole time.

    `Unavailable` is the right class: the call was well formed and permitted, this
    instance just is not configured to serve it, and nothing the caller does
    differently will change that.
    """
    where = f"{provider}" + (f" ({endpoint})" if endpoint else "")
    try:
        yield
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        body = (e.response.text or "")[:200]
        if status == 404 and model and model in body:
            raise errors.Unavailable(
                f"{where} has no model {model!r}",
                hint=f"pull it on the provider (`ollama pull {model}`) or correct the "
                     "model name in Settings -> AI providers; retrying will not help",
            ) from e
        raise errors.Unavailable(
            f"{where} returned HTTP {status}" + (f": {body}" if body else ""),
            hint="check the provider's credentials and model configuration in "
                 "Settings -> AI providers",
        ) from e
    except httpx.TimeoutException as e:
        raise errors.Unavailable(
            f"{where} timed out",
            hint="the model may be cold or the endpoint overloaded; this one IS worth "
                 "retrying, or raise LLM_TIMEOUT_SECONDS",
        ) from e
    except httpx.HTTPError as e:
        raise errors.Unavailable(
            f"cannot reach {where}: {type(e).__name__}",
            hint="correct the provider base URL in Settings -> AI providers. Note that "
                 "`localhost` resolves to the API CONTAINER, not the host — use the "
                 "host's name or address; retrying will not help",
        ) from e


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class ChatModel(Protocol):
    # `temperature=0` asks for a deterministic answer. Judging is not writing: a
    # classifier that returns a different verdict for identical input makes approval
    # depend on WHEN it ran. Providers that cannot honour it ignore it.
    def chat(self, *, system: str, context: str, question: str,
             temperature: float | None = None) -> str: ...


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
