def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_login_and_me(client):
    r = client.post("/api/auth/login", json={"email": "alex@ascme-labs.com", "password": "agentledger"})
    assert r.status_code == 200
    tok = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.json()["handle"] == "ascme"


def test_login_bad_password(client):
    r = client.post("/api/auth/login", json={"email": "alex@ascme-labs.com", "password": "nope"})
    assert r.status_code == 401


def test_items_require_auth(client):
    assert client.get("/api/items").status_code == 401


def test_seeded_items(client, auth):
    items = client.get("/api/items", headers=auth).json()
    assert len(items) == 9
    assert items[0]["id"] == "AL-12"  # sort_order 0


def test_create_and_update_item(client, auth):
    r = client.post("/api/items", json={"title": "New thing", "tags": ["x"], "effort": 3}, headers=auth)
    assert r.status_code == 201
    iid = r.json()["id"]
    assert iid == "AL-23"
    up = client.patch(f"/api/items/{iid}", json={"status": "in_progress"}, headers=auth)
    assert up.json()["status"] == "in_progress"


def test_invalid_status_rejected(client, auth):
    r = client.patch("/api/items/AL-12", json={"status": "banana"}, headers=auth)
    assert r.status_code == 422


def test_reorder(client, auth):
    items = client.get("/api/items", headers=auth).json()
    ids = [i["id"] for i in items]
    reversed_ids = list(reversed(ids))
    r = client.patch("/api/items/reorder", json={"ordered_ids": reversed_ids}, headers=auth)
    new_ids = [i["id"] for i in r.json()]
    assert new_ids == reversed_ids


def test_requests_vote_and_link(client, auth):
    reqs = client.get("/api/requests", headers=auth).json()
    assert len(reqs) == 5
    v = client.post("/api/requests/R-35/vote", json={"delta": 1}, headers=auth)
    assert v.json()["votes"] == 4
    ln = client.post("/api/requests/R-35/link", json={"item_id": "AL-12"}, headers=auth)
    assert ln.json()["status"] == "linked"
    assert ln.json()["linked_to"] == "AL-12"


def test_link_unknown_item_422(client, auth):
    r = client.post("/api/requests/R-35/link", json={"item_id": "AL-999"}, headers=auth)
    assert r.status_code == 422


def test_memory_search_ranks_relevant_first(client, auth):
    r = client.post(
        "/api/memory/search",
        json={"query": "pgvector single postgres container self-host", "top_k": 3},
        headers=auth,
    )
    hits = r.json()
    assert hits[0]["shard"]["id"] == "m1"
    assert hits[0]["score"] >= hits[-1]["score"]


def test_add_memory_then_searchable(client, auth):
    client.post(
        "/api/memory/shards",
        json={"text": "Chose Vite over Next for the decoupled SPA frontend", "scope": "global"},
        headers=auth,
    )
    r = client.post("/api/memory/search", json={"query": "vite spa frontend decoupled", "top_k": 1}, headers=auth)
    assert "Vite" in r.json()[0]["shard"]["text"]


def test_mcp_requires_key(client):
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_mcp_tools_and_call(client, auth):
    key = client.post("/api/api-keys", json={"name": "test"}, headers=auth).json()["plaintext"]
    hk = {"X-API-Key": key}
    tl = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=hk)
    names = [t["name"] for t in tl.json()["result"]["tools"]]
    assert names[:5] == ["create_item", "update_item", "search_items", "add_memory", "search_memory"]
    assert set(names) >= {
        "create_item", "update_item", "search_items", "add_memory", "search_memory",
        "get_backlog", "get_item_details", "suggest_next", "link_items", "extract_lessons",
        "generate_digest",
    }
    assert len(names) == 11

    call = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "create_item", "arguments": {"title": "From agent", "effort": 1}}},
        headers=hk,
    )
    import json
    payload = json.loads(call.json()["result"]["content"][0]["text"])
    assert payload["title"] == "From agent"

    # The agent-created item is visible through the web API — shared service layer.
    items = client.get("/api/items", headers=auth).json()
    assert any(i["title"] == "From agent" for i in items)


def test_register_then_create_first_project(client):
    # A brand-new user (as after a full data wipe) can register and stand up a workspace.
    r = client.post(
        "/api/auth/register",
        json={"name": "Sam Rivers", "email": "sam@example.com", "handle": "sam", "password": "pw123456"},
    )
    assert r.status_code == 201, r.text
    hdr = {"Authorization": f"Bearer {r.json()['access_token']}"}

    proj = client.post("/api/projects", json={"name": "My First Project", "accent": "#a78bfa"}, headers=hdr)
    assert proj.status_code == 201, proj.text
    body = proj.json()
    assert body["name"] == "My First Project"
    assert body["id"] == "my-first-project"  # slugified from the name

    # It shows up in the project list and the creator is a member.
    projects = client.get("/api/projects", headers=hdr).json()
    assert any(p["id"] == "my-first-project" for p in projects)
    members = client.get("/api/projects/my-first-project/members", headers=hdr).json()
    assert any(m["role"] == "owner" and m["user"]["email"] == "sam@example.com" for m in members)

    # Creating an item scoped to the new project works and lands there (not "core").
    it = client.post(
        "/api/items",
        json={"title": "First task", "effort": 2, "project_id": "my-first-project"},
        headers=hdr,
    )
    assert it.status_code == 201, it.text
    assert it.json()["project_id"] == "my-first-project"
    listed = client.get("/api/items?project_id=my-first-project", headers=hdr).json()
    assert [i["title"] for i in listed] == ["First task"]


def test_create_item_unknown_project_is_422(client, auth):
    # A missing/incorrect project is a clean client error, not a 500.
    r = client.post("/api/items", json={"title": "x", "project_id": "does-not-exist"}, headers=auth)
    assert r.status_code == 422


def test_create_project_slug_collision(client, auth):
    a = client.post("/api/projects", json={"name": "Duplicate"}, headers=auth).json()
    b = client.post("/api/projects", json={"name": "Duplicate"}, headers=auth).json()
    assert a["id"] == "duplicate"
    assert b["id"] == "duplicate-2"
