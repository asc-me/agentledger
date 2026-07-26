"""AL-176: per-conversation model picker — selectable providers + per-provider resolution."""
import pytest

from app.db import SessionLocal
from app.providers.openai_compat import OpenAICompatChat
from app.providers.stub import StubChat
from app.services import assistant as asst
from app.services import platform as platform_svc


@pytest.fixture()
def db(client):
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def test_selectable_providers_flags_configured_and_active(client, auth, db):
    # Configure openai (a real provider) via the platform API — sets a key + marks active.
    client.patch("/api/platform", json={
        "active_chat_provider": "openai",
        "providers": {"openai": {"api_key": "sk-x", "chat_model": "gpt-4o-mini"}},
    }, headers=auth)

    provs = {p["id"]: p for p in platform_svc.selectable_providers(db, "core")}
    assert "stub" not in provs  # the offline stub is never an assistant model
    assert provs["openai"]["configured"] is True and provs["openai"]["active"] is True
    assert provs["anthropic"]["configured"] is False  # no key configured → not selectable
    assert provs["xai"]["configured"] is False
    # a single-model provider still exposes a one-element models list
    assert provs["openai"]["models"] == ["gpt-4o-mini"]


def test_xai_catalog_lists_grok_build_and_defaults_to_grok_45(client, auth, db):
    client.patch("/api/platform", json={"providers": {"xai": {"api_key": "sk-grok"}}}, headers=auth)
    xai = next(p for p in platform_svc.selectable_providers(db, "core") if p["id"] == "xai")
    assert xai["chat_model"] == "grok-4.5"  # default bumped off the stale grok-2-latest
    assert xai["models"] == ["grok-4.5", "grok-build-0.1"]  # coding model selectable in the picker


def test_a_configured_custom_model_stays_selectable(client, auth, db):
    # a per-project chat_model that isn't in the registry list is prepended, not dropped
    client.patch("/api/platform", json={
        "providers": {"xai": {"api_key": "sk-grok", "chat_model": "grok-9-experimental"}}}, headers=auth)
    xai = next(p for p in platform_svc.selectable_providers(db, "core") if p["id"] == "xai")
    assert xai["chat_model"] == "grok-9-experimental"
    assert xai["models"][0] == "grok-9-experimental" and "grok-build-0.1" in xai["models"]


def test_resolve_chat_for_grok_build_coding_model(client, auth, db):
    client.patch("/api/platform", json={
        "providers": {"xai": {"api_key": "sk-grok", "chat_model": "grok-build-0.1"}}}, headers=auth)
    provider, chat = platform_svc.resolve_chat_for(db, "core", "xai")
    assert provider == "xai" and chat.model == "grok-build-0.1"
    assert chat.base_url == "https://api.x.ai/v1"  # coding model on the xAI OpenAI-compat endpoint


def test_resolve_chat_for_builds_the_chosen_provider(client, auth, db):
    client.patch("/api/platform", json={
        "active_chat_provider": "openai",
        "providers": {
            "openai": {"api_key": "sk-openai", "chat_model": "gpt-4o-mini"},
            "xai": {"api_key": "sk-grok", "chat_model": "grok-2-latest"},
        },
    }, headers=auth)

    # A thread can pick a DIFFERENT provider than the project's active one.
    provider, chat = platform_svc.resolve_chat_for(db, "core", "xai")
    assert provider == "xai" and isinstance(chat, OpenAICompatChat)
    assert chat.model == "grok-2-latest" and chat.api_key == "sk-grok"
    assert chat.base_url == "https://api.x.ai/v1"  # registry default when none saved


def test_resolve_chat_for_unconfigured_pick_degrades_to_stub(db):
    provider, chat = platform_svc.resolve_chat_for(db, "core", "stub")
    assert provider == "stub" and isinstance(chat, StubChat)


def test_set_thread_model_pins_the_provider(db):
    thread = asst.create_thread(db, project_id="core", entity_type="item", entity_id="AL-08")
    asst.set_thread_model(db, thread.id, provider="anthropic", model="claude-opus-4-8")
    reloaded = asst.get_thread(db, thread.id)
    assert reloaded.provider == "anthropic" and reloaded.model == "claude-opus-4-8"
