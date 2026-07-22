"""Phase 5: platform/AI-provider settings, integrations config, GitHub webhook, project/member settings."""


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


def test_webhook_routes_to_connected_project_and_links_issue(client, auth):
    # Connect a repo to a specific (non-default) project.
    client.post("/api/projects", json={"name": "Site"}, headers=auth)  # id: site
    client.post(
        "/api/platform/github/connect?project_id=site",
        json={"account": "acme", "repo": "acme/website"}, headers=auth,
    )
    r = client.post(
        "/api/public/github/webhook",
        json={"action": "opened",
              "repository": {"full_name": "acme/website"},
              "issue": {"title": "Hero broken", "html_url": "https://github.com/acme/website/issues/9"}},
    )
    body = r.json()
    assert body["project_id"] == "site"  # routed by repo
    assert body["github_url"] == "https://github.com/acme/website/issues/9"
    created = next(i for i in client.get("/api/items?project_id=site", headers=auth).json()
                   if i["id"] == body["created_item"])
    assert created["github_url"] == "https://github.com/acme/website/issues/9"


def test_item_github_url_via_patch(client, auth):
    r = client.patch("/api/items/AL-12",
                     json={"github_url": "https://github.com/acme/x/pull/42"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["github_url"] == "https://github.com/acme/x/pull/42"


def test_platform_exposes_sitekey_not_secret(client, auth):
    client.patch("/api/platform?project_id=core",
                 json={"turnstile_sitekey": "0xSITE", "turnstile_secret": "0xSECRET", "rate_limit_per_min": 5},
                 headers=auth)
    cfg = client.get("/api/platform?project_id=core", headers=auth).json()
    assert cfg["turnstile_sitekey"] == "0xSITE"
    assert cfg["turnstile_secret_set"] is True
    assert cfg["rate_limit_per_min"] == 5
    assert "turnstile_secret" not in cfg  # the secret is never returned
