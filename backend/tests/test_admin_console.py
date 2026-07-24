"""AL-94: the operator console's API surface.

Everything here is gated twice (hosted + platform-admin allowlist) and 404s otherwise,
and returns METADATA ONLY — orgs, plans, usage, identity. The exhaustive
no-tenant-content / audit matrix lives in AL-95; these cover the endpoints themselves.
"""
import pytest

SEED_PW = "agentledger"
ADMIN_EMAIL = "alex@ascme-labs.com"


def _login(client, email, password=SEED_PW):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def operator(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_mode", True)
    monkeypatch.setattr(settings, "platform_admin_emails", ADMIN_EMAIL)
    return _login(client, ADMIN_EMAIL)


# ---- gating --------------------------------------------------------------------
ADMIN_GETS = ["/api/admin/me", "/api/admin/orgs", "/api/admin/users",
              "/api/admin/invites", "/api/admin/org-requests"]


def test_every_admin_route_404s_for_non_admin(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_mode", True)
    monkeypatch.setattr(settings, "platform_admin_emails", "")  # nobody is an operator
    auth = _login(client, ADMIN_EMAIL)
    for path in ADMIN_GETS:
        assert client.get(path, headers=auth).status_code == 404, path


def test_every_admin_route_404s_on_self_host(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "platform_admin_emails", ADMIN_EMAIL)
    auth = _login(client, ADMIN_EMAIL)
    for path in ADMIN_GETS:
        assert client.get(path, headers=auth).status_code == 404, path


def test_admin_routes_require_auth(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_mode", True)
    for path in ADMIN_GETS:
        assert client.get(path).status_code == 401, path


def test_whoami_identifies_the_operator(client, operator):
    body = client.get("/api/admin/me", headers=operator).json()
    assert body["is_platform_admin"] is True
    assert body["email"] == ADMIN_EMAIL


# ---- orgs ----------------------------------------------------------------------
def test_org_listing_reports_owner_plan_and_usage(client, operator):
    org = client.post("/api/orgs", json={"name": "Acme"}, headers=operator).json()
    client.post("/api/projects", json={"name": "Rocket"}, headers=operator)

    rows = client.get("/api/admin/orgs", headers=operator).json()
    row = next(r for r in rows if r["id"] == org["id"])
    assert row["name"] == "Acme"
    assert row["owner_email"] == ADMIN_EMAIL
    assert row["plan"] == "free"
    assert row["usage"]["projects"] == 1
    assert row["usage"]["seats"] == 1
    assert row["limits"]["max_projects"] > 0


def test_org_listing_spans_tenants(client, operator):
    """The operator sees every tenant — that's the point of the plane."""
    client.post("/api/orgs", json={"name": "Acme"}, headers=operator)
    dana = _login(client, "dana@ascme-labs.com")
    client.post("/api/orgs", json={"name": "Beta Co"}, headers=dana)
    names = {r["name"] for r in client.get("/api/admin/orgs", headers=operator).json()}
    assert {"Acme", "Beta Co"} <= names


def test_org_listing_exposes_no_tenant_content(client, operator):
    """Metadata only — the isolation boundary. No item/memory/prd fields anywhere."""
    client.post("/api/orgs", json={"name": "Acme"}, headers=operator)
    pid = client.post("/api/projects", json={"name": "Rocket"}, headers=operator).json()["id"]
    client.post("/api/items", json={"title": "secret item", "project_id": pid}, headers=operator)
    client.post("/api/memory/shards", json={"text": "secret memory", "project_id": pid},
                headers=operator)

    blob = client.get("/api/admin/orgs", headers=operator).text
    assert "secret item" not in blob
    assert "secret memory" not in blob


def test_plan_assignment_reflects_in_org_listing(client, operator):
    org = client.post("/api/orgs", json={"name": "Acme"}, headers=operator).json()
    client.put(f"/api/orgs/{org['id']}/plan", json={"plan": "team"}, headers=operator)
    rows = client.get("/api/admin/orgs", headers=operator).json()
    assert next(r for r in rows if r["id"] == org["id"])["plan"] == "team"


# ---- users ---------------------------------------------------------------------
def test_user_listing_is_identity_plus_org_count(client, operator):
    client.post("/api/orgs", json={"name": "Acme"}, headers=operator)
    rows = client.get("/api/admin/users", headers=operator).json()
    me = next(r for r in rows if r["email"] == ADMIN_EMAIL)
    assert me["handle"] == "ascme"
    assert me["org_count"] == 1
    # No credential material ever leaves the plane.
    assert "password_hash" not in me and "token_version" not in me
