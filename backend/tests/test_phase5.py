"""Phase 5: platform/AI-provider settings, integrations config, GitHub webhook, project/member settings."""
import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.routers import public
    public._hits.clear()
    yield
    public._hits.clear()


def test_platform_config_seeded(client, auth):
    cfg = client.get("/api/platform", headers=auth).json()
    assert cfg["llm_mode"] == "stub"
    assert cfg["github_connected"] is True
    assert cfg["github_repo"] == "ascme-labs/agentledger"
    assert cfg["cloud_model"] == "claude-opus-4-8"


def test_switch_llm_provider_drives_f1(client, auth):
    from app.config import settings
    client.patch("/api/platform", json={"llm_mode": "cloud"}, headers=auth)
    assert settings.chat_provider == "anthropic"  # applied to the live provider
    back = client.patch("/api/platform", json={"llm_mode": "stub"}, headers=auth).json()
    assert back["llm_mode"] == "stub"
    assert settings.chat_provider == "stub"


def test_invalid_llm_mode_rejected(client, auth):
    assert client.patch("/api/platform", json={"llm_mode": "gpt"}, headers=auth).status_code == 422


def test_github_connect_disconnect(client, auth):
    client.post("/api/platform/github/disconnect", headers=auth)
    c = client.post("/api/platform/github/connect", json={"account": "acme", "repo": "acme/app"}, headers=auth).json()
    assert c["github_connected"] is True and c["github_repo"] == "acme/app"
    d = client.post("/api/platform/github/disconnect", headers=auth).json()
    assert d["github_connected"] is False and d["github_repo"] == ""


def test_github_create_issue_creates_item(client, auth):
    r = client.post(
        "/api/platform/github/create-issue",
        json={"title": "Support dark mode toggle", "body": "add a toggle", "type": "feature"},
        headers=auth,
    ).json()
    assert r["item"]["id"].startswith("AL-")
    assert r["pushed_to_github"] is False
    assert "ascme-labs/agentledger" in r["detail"]  # connected repo named


def test_gdrive_connect(client, auth):
    c = client.post("/api/platform/gdrive/connect", json={"account": "me@x.com", "folder": "/PRDs"}, headers=auth).json()
    assert c["gdrive_connected"] is True and c["gdrive_folder"] == "/PRDs"


def test_project_update_and_members(client, auth):
    up = client.patch("/api/projects/core", json={"name": "Core!", "auto_extract": False}, headers=auth).json()
    assert up["name"] == "Core!" and up["auto_extract"] is False
    members = client.get("/api/projects/core/members", headers=auth).json()
    assert len(members) == 4
    owner = [m for m in members if m["role"] == "owner"]
    assert owner and owner[0]["user"]["handle"] == "ascme"


def test_github_webhook_creates_item_no_auth(client, auth):
    before = len(client.get("/api/items", headers=auth).json())
    r = client.post(
        "/api/public/github/webhook",
        json={"action": "opened", "issue": {"title": "Crash on startup", "body": "stack trace..."}},
    )  # no Authorization header
    assert r.status_code == 200
    new_id = r.json()["created_item"]
    items = client.get("/api/items", headers=auth).json()
    assert len(items) == before + 1
    created = next(i for i in items if i["id"] == new_id)
    assert created["title"] == "Crash on startup"
    assert "github" in created["tags"]


def test_webhook_ignores_non_open_actions(client):
    r = client.post("/api/public/github/webhook", json={"action": "closed", "issue": {"title": "x"}})
    assert r.json()["ignored"] is True
