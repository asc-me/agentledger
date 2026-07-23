"""SaaS-arc Phase 5 (slice A): Railway readiness, rate limiting, observability.

Covers the unit-testable code — DATABASE_URL normalization, the request-id
middleware, the rate-limiter front door (in-process fallback), and the hosted
per-org MCP burst cap. Docker/nginx/railway.json plumbing is verified at deploy time.
"""
import pytest


# ---- DATABASE_URL normalization (AL-26) ---------------------------------------
@pytest.mark.parametrize(
    "given,expected",
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql+psycopg://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("sqlite:///./x.db", "sqlite:///./x.db"),
    ],
)
def test_database_url_normalized(given, expected):
    from app.config import Settings

    assert Settings(database_url=given, _env_file=None).database_url == expected


# ---- request-id middleware (AL-56) --------------------------------------------
def test_request_id_generated_when_absent(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    rid = r.headers.get("x-request-id")
    assert rid and len(rid) >= 8


def test_request_id_echoed_when_provided(client):
    r = client.get("/api/config", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers.get("x-request-id") == "trace-abc-123"


# ---- rate-limit front door (in-process fallback) ------------------------------
def test_ratelimit_allow_blocks_over_limit():
    from app.services import ratelimit, spam

    spam._hits.clear()
    key = "test:ratelimit:key"
    assert ratelimit.allow(key, 2) is True
    assert ratelimit.allow(key, 2) is True
    assert ratelimit.allow(key, 2) is False  # third within the window is blocked


# ---- hosted per-org MCP burst cap ---------------------------------------------
def _mcp(client, key, tool):
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool, "arguments": {}}},
        headers={"X-API-Key": key},
    ).json()


def test_org_rate_cap_trips_rate_limited(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_mode", True)
    monkeypatch.setattr(settings, "org_rate_per_min", 2)

    r = client.post("/api/auth/login", json={"email": "alex@ascme-labs.com", "password": "agentledger"})
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    client.post("/api/orgs", json={"name": "Acme"}, headers=auth)
    client.post("/api/projects", json={"name": "Rocket"}, headers=auth)
    key = client.post("/api/api-keys", json={"name": "agent"}, headers=auth).json()["plaintext"]

    _mcp(client, key, "get_backlog")
    _mcp(client, key, "get_backlog")
    third = _mcp(client, key, "get_backlog")["result"]
    assert third.get("isError") is True
    assert third["structuredContent"]["error"]["code"] == "rate_limited"


def test_org_rate_cap_off_self_host(client, monkeypatch):
    """With hosted_mode off, the per-org cap never engages."""
    from app.config import settings

    monkeypatch.setattr(settings, "org_rate_per_min", 1)  # would bite if hosted
    auth_r = client.post("/api/auth/login", json={"email": "alex@ascme-labs.com", "password": "agentledger"})
    auth = {"Authorization": f"Bearer {auth_r.json()['access_token']}"}
    key = client.post("/api/api-keys", json={"name": "agent"}, headers=auth).json()["plaintext"]
    for _ in range(3):
        assert "error" not in _mcp(client, key, "get_backlog")["result"].get("structuredContent", {})
