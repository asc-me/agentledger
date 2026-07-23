"""AL-43: the audit ledger records who did what, and reads back scoped to the
caller's readable projects."""


def _login(client, email="alex@ascme-labs.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _key(client, auth, **body):
    return client.post("/api/api-keys", json={"name": "a", **body}, headers=auth).json()["plaintext"]


def _mcp(client, key, tool, args):
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool, "arguments": args}},
        headers={"X-API-Key": key},
    ).json()["result"]


def _events(client, auth, **params):
    return client.get("/api/events", params=params, headers=auth).json()


def test_mcp_write_is_audited_with_key_actor(client, auth):
    key = _key(client, auth, project_id="core")
    created = _mcp(client, key, "create_item", {"title": "audited"})["structuredContent"]
    ev = _events(client, auth, project_id="core")
    top = ev["results"][0]
    assert top["action"] == "create_item"
    assert top["actor_type"] == "apikey"
    assert top["actor_label"] == "a"
    assert top["target_id"] == created["id"]
    assert top["surface"] == "mcp"


def test_mcp_read_is_not_audited(client, auth):
    key = _key(client, auth, project_id="core")
    before = _events(client, auth, project_id="core")["total"]
    _mcp(client, key, "search_items", {"query": "x"})
    after = _events(client, auth, project_id="core")["total"]
    assert after == before


def test_rest_key_lifecycle_is_audited(client, auth):
    created = client.post("/api/api-keys", json={"name": "temp", "project_id": "core"}, headers=auth).json()
    client.delete(f"/api/api-keys/{created['id']}", headers=auth)
    actions = [e["action"] for e in _events(client, auth, project_id="core")["results"]]
    assert "create_api_key" in actions
    assert "revoke_api_key" in actions


def test_project_update_is_audited(client, auth):
    client.patch("/api/projects/core", json={"description": "changed"}, headers=auth)
    top = _events(client, auth, project_id="core", action="update_project")["results"][0]
    assert top["actor_type"] == "user"
    assert "description" in top["meta"]["fields"]


def test_events_scoped_to_readable_projects(client):
    # ops: read core, none on web. Create a web event as alex, ensure ops can't see web,
    # and can't even query web's ledger.
    alex = _login(client, "alex@ascme-labs.com")
    kate_web_key = _key(client, alex, project_id="web")
    _mcp(client, kate_web_key, "create_item", {"title": "web item"})

    ops = _login(client, "ops@ascme-labs.com")
    # ops querying web directly → 404 (existence-hiding)
    assert client.get("/api/events", params={"project_id": "web"}, headers=ops).status_code == 404
    # ops's default (all-readable) ledger never includes web events
    all_ops = _events(client, ops)
    assert all(e["project_id"] != "web" for e in all_ops["results"])


def test_events_paginated_newest_first(client, auth):
    key = _key(client, auth, project_id="core")
    for i in range(3):
        _mcp(client, key, "create_item", {"title": f"n{i}"})
    page = _events(client, auth, project_id="core", limit=2)
    assert page["limit"] == 2 and page["has_more"] is True
    ids = [e["id"] for e in page["results"]]
    assert ids == sorted(ids, reverse=True)
