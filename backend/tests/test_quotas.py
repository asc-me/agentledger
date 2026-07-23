"""AL-75: plan limits + quota enforcement (hosted-only).

Limits are monkeypatched to tiny values so the caps are easy to hit. All runs pin
``settings.hosted_mode = True`` except the self-host test, which proves quotas are
inert off hosted mode.
"""
import pytest

from app.services import quotas


def _login(client, email, password="agentledger"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_org(client, headers, name="Acme"):
    r = client.post("/api/orgs", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def hosted(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_mode", True)
    return settings


def _set_plan(monkeypatch, tier="free", **limits):
    base = quotas.PLANS[tier]
    monkeypatch.setitem(
        quotas.PLANS,
        tier,
        quotas.Plan(
            max_projects=limits.get("max_projects", base.max_projects),
            max_seats=limits.get("max_seats", base.max_seats),
            max_shards=limits.get("max_shards", base.max_shards),
            max_calls_per_month=limits.get("max_calls_per_month", base.max_calls_per_month),
        ),
    )


# ---- self-host: quotas inert ---------------------------------------------------
def test_self_host_has_no_quotas(client, monkeypatch):
    _set_plan(monkeypatch, max_projects=1)  # would bite in hosted mode
    auth = _login(client, "alex@ascme-labs.com")
    for i in range(3):
        assert client.post("/api/projects", json={"name": f"P{i}"}, headers=auth).status_code == 201


# ---- project / seat / shard caps ----------------------------------------------
def test_project_cap(client, hosted, monkeypatch):
    _set_plan(monkeypatch, max_projects=1)
    auth = _login(client, "alex@ascme-labs.com")
    _make_org(client, auth)
    assert client.post("/api/projects", json={"name": "One"}, headers=auth).status_code == 201
    r = client.post("/api/projects", json={"name": "Two"}, headers=auth)
    assert r.status_code == 402
    assert "project limit" in r.json()["detail"]


def test_seat_cap_counts_members_plus_pending(client, hosted, monkeypatch):
    _set_plan(monkeypatch, max_seats=2)  # owner = 1 seat, so exactly 1 invite fits
    auth = _login(client, "alex@ascme-labs.com")
    org = _make_org(client, auth)
    assert client.post(f"/api/orgs/{org['id']}/invites",
                       json={"email": "a@example.com"}, headers=auth).status_code == 201
    r = client.post(f"/api/orgs/{org['id']}/invites", json={"email": "b@example.com"}, headers=auth)
    assert r.status_code == 402
    assert "seat limit" in r.json()["detail"]


def test_shard_cap(client, hosted, monkeypatch):
    _set_plan(monkeypatch, max_shards=1)
    auth = _login(client, "alex@ascme-labs.com")
    _make_org(client, auth)
    pid = client.post("/api/projects", json={"name": "Rocket"}, headers=auth).json()["id"]
    assert client.post("/api/memory/shards",
                       json={"text": "first", "project_id": pid}, headers=auth).status_code == 201
    r = client.post("/api/memory/shards", json={"text": "second", "project_id": pid}, headers=auth)
    assert r.status_code == 402
    assert "memory limit" in r.json()["detail"]


# ---- monthly MCP call cap ------------------------------------------------------
def _mcp(client, key, tool, arguments=None):
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool, "arguments": arguments or {}}},
        headers={"X-API-Key": key},
    ).json()


def test_monthly_call_cap(client, hosted, monkeypatch):
    _set_plan(monkeypatch, max_calls_per_month=2)
    auth = _login(client, "alex@ascme-labs.com")
    _make_org(client, auth)
    client.post("/api/projects", json={"name": "Rocket"}, headers=auth)  # org's sole reachable project
    key = client.post("/api/api-keys", json={"name": "agent"}, headers=auth).json()["plaintext"]

    # Two metered calls succeed; the third trips the cap with a typed tool error.
    assert "error" not in _mcp(client, key, "get_backlog")["result"].get("structuredContent", {})
    _mcp(client, key, "get_backlog")
    third = _mcp(client, key, "get_backlog")["result"]
    assert third.get("isError") is True
    assert third["structuredContent"]["error"]["code"] == "quota_exceeded"


# ---- billing status + manual plan assignment ----------------------------------
def test_billing_status_shape(client, hosted, monkeypatch):
    _set_plan(monkeypatch, max_projects=5, max_seats=5)
    auth = _login(client, "alex@ascme-labs.com")
    org = _make_org(client, auth)
    client.post("/api/projects", json={"name": "Rocket"}, headers=auth)
    r = client.get(f"/api/orgs/{org['id']}/billing", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "free"
    assert body["limits"]["max_projects"] == 5
    assert body["usage"]["projects"] == 1
    assert body["usage"]["seats"] == 1  # just the owner


def test_plan_assignment_requires_platform_admin(client, hosted, monkeypatch):
    auth = _login(client, "alex@ascme-labs.com")
    org = _make_org(client, auth)
    # Org owner is NOT a platform admin → endpoint hidden (404).
    assert client.put(f"/api/orgs/{org['id']}/plan", json={"plan": "team"}, headers=auth).status_code == 404

    # Operator allowlists alex → assignment works and takes effect.
    from app.config import settings

    monkeypatch.setattr(settings, "platform_admin_emails", "alex@ascme-labs.com")
    r = client.put(f"/api/orgs/{org['id']}/plan", json={"plan": "team"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["plan"] == "team"
    assert client.get(f"/api/orgs/{org['id']}/billing", headers=auth).json()["plan"] == "team"


def test_plan_assignment_rejects_unknown_plan(client, hosted, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "platform_admin_emails", "alex@ascme-labs.com")
    auth = _login(client, "alex@ascme-labs.com")
    org = _make_org(client, auth)
    assert client.put(f"/api/orgs/{org['id']}/plan", json={"plan": "enterprise"}, headers=auth).status_code == 422


def test_upgraded_plan_lifts_the_cap(client, hosted, monkeypatch):
    """After a manual upgrade, a previously-blocked create succeeds."""
    _set_plan(monkeypatch, tier="free", max_projects=1)
    _set_plan(monkeypatch, tier="team", max_projects=10)
    from app.config import settings

    monkeypatch.setattr(settings, "platform_admin_emails", "alex@ascme-labs.com")
    auth = _login(client, "alex@ascme-labs.com")
    org = _make_org(client, auth)
    client.post("/api/projects", json={"name": "One"}, headers=auth)
    assert client.post("/api/projects", json={"name": "Two"}, headers=auth).status_code == 402
    client.put(f"/api/orgs/{org['id']}/plan", json={"plan": "team"}, headers=auth)
    assert client.post("/api/projects", json={"name": "Two"}, headers=auth).status_code == 201
