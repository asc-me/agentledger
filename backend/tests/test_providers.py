"""AI provider registry — list, per-provider config (write-only keys), and live resolution.
No network: we assert on the constructed adapter, never call .chat()."""
import app.providers as providers
from app.providers.openai_compat import OpenAICompatChat


def test_provider_registry_endpoint(client, auth):
    r = client.get("/api/platform/providers", headers=auth)
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()["providers"]}
    assert {"stub", "anthropic", "openai", "ollama", "groq", "deepseek", "mistral", "xai", "gemini"} <= ids


def test_set_active_provider_config_redacted_and_live(client, auth):
    r = client.patch(
        "/api/platform",
        json={
            "active_chat_provider": "openai",
            "providers": {"openai": {"api_key": "sk-test-123", "chat_model": "gpt-4o-mini",
                                     "base_url": "https://api.openai.com/v1"}},
        },
        headers=auth,
    )
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["active_chat_provider"] == "openai"
    pc = cfg["provider_config"]["openai"]
    assert pc["key_set"] is True and pc["chat_model"] == "gpt-4o-mini"
    assert "api_key" not in pc  # redacted — never returned raw
    # drives the live provider layer
    assert providers._active["provider"] == "openai"
    assert providers._active["api_key"] == "sk-test-123"


def test_provider_key_is_write_only(client, auth):
    client.patch("/api/platform", json={
        "active_chat_provider": "openai",
        "providers": {"openai": {"api_key": "sk-keep", "chat_model": "gpt-4o-mini"}},
    }, headers=auth)
    # change the model with a blank key → the stored key survives
    r = client.patch("/api/platform", json={"providers": {"openai": {"chat_model": "gpt-4o", "api_key": ""}}}, headers=auth)
    pc = r.json()["provider_config"]["openai"]
    assert pc["key_set"] is True and pc["chat_model"] == "gpt-4o"
    assert providers._active["api_key"] == "sk-keep"


def test_ollama_rich_config_drives_provider(client, auth):
    r = client.patch("/api/platform", json={
        "active_chat_provider": "ollama",
        "providers": {"ollama": {"base_url": "https://ollama.example.ts.net", "chat_model": "qwen2.5",
                                 "embed_model": "nomic-embed-text", "api_key": "caddy-bearer"}},
    }, headers=auth)
    assert r.status_code == 200
    cm = providers.get_chat_model()
    assert cm.base_url == "https://ollama.example.ts.net"
    assert cm.model == "qwen2.5"
    assert cm.auth_key == "caddy-bearer"


def test_openai_compat_provider_uses_registry_default_base(client, auth):
    client.patch("/api/platform", json={
        "active_chat_provider": "groq",
        "providers": {"groq": {"api_key": "gk", "chat_model": "llama-3.3-70b-versatile"}},
    }, headers=auth)
    cm = providers.get_chat_model()
    assert isinstance(cm, OpenAICompatChat)
    assert cm.base_url == "https://api.groq.com/openai/v1"  # default from the registry
    assert cm.model == "llama-3.3-70b-versatile" and cm.api_key == "gk"


def test_unknown_provider_rejected(client, auth):
    assert client.patch("/api/platform", json={"active_chat_provider": "nope"}, headers=auth).status_code == 422
