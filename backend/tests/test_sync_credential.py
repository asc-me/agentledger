"""AL-219 D4: minting the org-issued `sync` credential from the UI.

The credential a local self-host instance authenticates with is just an API key with the
`sync` scope pinned to one project. These tests cover the guards that make it safe to hand
to a Cursor Team, since the key is distributed far wider than a personal agent key:

- pinned to exactly ONE project (a global sync key would resolve to every project its owner
  can write — the blast radius the per-project decision in D6 exists to avoid),
- its owner needs WRITE on that project (ingest writes; read-only would mint a dead key that
  only fails later at push time),
- the scope vocabulary is validated (a typo'd scope silently produces a key that can never sync).

Seeded fixtures (seed.py): alex = write on core/web/infra; ops = read on core, write on infra.
"""


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_NODES = [
    {"path": "backend/app/routers/apikeys.py", "kind": "file", "name": "api keys",
     "summary": "Mint and revoke scoped API keys.", "content_hash": "c1"},
]


def test_mint_sync_credential_pins_to_project_and_can_ingest(client, auth):
    r = client.post("/api/api-keys",
                    json={"name": "laptop — core", "scopes": ["sync"], "project_id": "core"},
                    headers=auth)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["scopes"] == ["sync"]
    assert body["project_id"] == "core"
    key = body["plaintext"]

    # The credential works end-to-end: ingest resolves its target server-side from the key.
    push = client.post("/api/sync/code-graph", json={"nodes": _NODES, "edges": []},
                       headers={"X-API-Key": key})
    assert push.status_code == 200, push.text
    assert push.json()["project_id"] == "core"


def test_global_sync_credential_is_rejected(client, auth):
    """Unpinned, `key_sync_ids` would fall back to every writable project."""
    r = client.post("/api/api-keys",
                    json={"name": "everywhere", "scopes": ["sync"], "project_id": None},
                    headers=auth)
    assert r.status_code == 422
    assert "one project" in r.text


def test_unknown_scope_is_rejected(client, auth):
    """'Sync' never matches the `"sync" in key.scopes` check — fail at mint, not at push."""
    r = client.post("/api/api-keys",
                    json={"name": "typo", "scopes": ["Sync"], "project_id": "core"},
                    headers=auth)
    assert r.status_code == 422
    assert "unknown scope" in r.text.lower()


def test_sync_credential_requires_write_not_just_read(client):
    ops = _login(client, "ops@ascme-labs.com")  # core access: read-only
    r = client.post("/api/api-keys",
                    json={"name": "readonly", "scopes": ["sync"], "project_id": "core"},
                    headers=ops)
    assert r.status_code == 403
    # …but the same user CAN mint one where they have write.
    ok = client.post("/api/api-keys",
                     json={"name": "infra", "scopes": ["sync"], "project_id": "infra"},
                     headers=ops)
    assert ok.status_code == 201, ok.text


def test_agent_key_minting_is_unchanged(client, auth):
    """The default path must not have picked up the sync guards — a global agent key is fine."""
    r = client.post("/api/api-keys", json={"name": "ci-agent", "project_id": None}, headers=auth)
    assert r.status_code == 201, r.text
    assert r.json()["scopes"] == ["read", "write"]
