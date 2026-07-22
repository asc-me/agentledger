"""AI provider registry — the catalog the Settings UI lists and the provider layer
resolves against. One entry per provider; `kind` picks the adapter:

- `stub`     — deterministic offline (no config)
- `anthropic`— native Claude SDK
- `openai`   — any OpenAI-compatible /chat/completions API (OpenAI, Groq, DeepSeek,
               Mistral, xAI, Gemini's compat endpoint) — base_url + api_key + model
- `ollama`   — local/self-hosted Ollama (base_url, optional bearer for a Caddy-guarded
               endpoint, chat + embedding models)

`embeds` marks providers that can also serve embeddings. NOTE: switching the embedding
provider/model changes the vector dimension, so it stays a deploy-time choice (EMBED_PROVIDER
+ EMBED_DIM) — only the base_url/model are read from this config.
"""
from __future__ import annotations

PROVIDERS: list[dict] = [
    {"id": "stub", "label": "Offline stub", "kind": "stub", "embeds": True,
     "base_url": "", "chat_model": "", "embed_model": "", "auth": False},
    {"id": "anthropic", "label": "Anthropic", "kind": "anthropic", "embeds": False,
     "base_url": "", "chat_model": "claude-opus-4-8", "embed_model": "", "auth": True},
    {"id": "openai", "label": "OpenAI", "kind": "openai", "embeds": True,
     "base_url": "https://api.openai.com/v1", "chat_model": "gpt-4o-mini",
     "embed_model": "text-embedding-3-small", "auth": True},
    {"id": "gemini", "label": "Google Gemini", "kind": "openai", "embeds": True,
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "chat_model": "gemini-2.0-flash", "embed_model": "text-embedding-004", "auth": True},
    {"id": "xai", "label": "xAI Grok", "kind": "openai", "embeds": False,
     "base_url": "https://api.x.ai/v1", "chat_model": "grok-2-latest", "embed_model": "", "auth": True},
    {"id": "groq", "label": "Groq", "kind": "openai", "embeds": False,
     "base_url": "https://api.groq.com/openai/v1", "chat_model": "llama-3.3-70b-versatile",
     "embed_model": "", "auth": True},
    {"id": "deepseek", "label": "DeepSeek", "kind": "openai", "embeds": False,
     "base_url": "https://api.deepseek.com/v1", "chat_model": "deepseek-chat", "embed_model": "", "auth": True},
    {"id": "mistral", "label": "Mistral", "kind": "openai", "embeds": False,
     "base_url": "https://api.mistral.ai/v1", "chat_model": "mistral-large-latest", "embed_model": "", "auth": True},
    {"id": "ollama", "label": "Ollama", "kind": "ollama", "embeds": True,
     "base_url": "http://localhost:11434", "chat_model": "llama3.1:8b",
     "embed_model": "nomic-embed-text", "auth": True},
]

_BY_ID = {p["id"]: p for p in PROVIDERS}
IDS = set(_BY_ID)
OPENAI_COMPAT = {p["id"] for p in PROVIDERS if p["kind"] == "openai"}


def get(pid: str) -> dict | None:
    return _BY_ID.get(pid)


def is_openai_compat(pid: str) -> bool:
    return pid in OPENAI_COMPAT


def kind(pid: str) -> str:
    p = _BY_ID.get(pid)
    return p["kind"] if p else "stub"
