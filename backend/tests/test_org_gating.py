"""AL-92: founding an organization is gated; additional orgs are requested or licensed.

Every account gets ONE org. Founding another needs either a standing plan entitlement
(the enterprise tier) or an operator-approved one-time request. This closes a real hole:
`POST /api/orgs` was previously ungated, so any authenticated user could spawn unlimited
tenants. Self-host keeps no limits at all.
"""
import pytest

SEED_PW = "agentledger"
ADMIN_EMAIL = "alex@ascme-labs.com"


def _login(client, email, password=SEED_PW):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def hosted(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_mode", True)
    return settings


@pytest.fixture()
def operator(client, hosted, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "platform_admin_emails", ADMIN_EMAIL)
    return _login(client, ADMIN_EMAIL)


def _entitle(monkeypatch, tier="free"):
    """Give a tier the standing multi-org entitlement."""
    from app.services import quotas

    monkeypatch.setitem(
        quotas.PLANS, tier,
        quotas.Plan(**{**quotas.PLANS[tier].__dict__, "may_found_additional_orgs": True}),
    )


# ---- the gate ------------------------------------------------------------------
def test_gate_is_inert_off_hosted_mode(client, monkeypatch):
    """Self-host never sees this gate. The org *router* already 404s with HOSTED_MODE
    off (AL-74), so this asserts the gate itself at the service level: inert when
    hosted mode is off, enforcing once it's on — the same user, same memberships."""
    from fastapi import HTTPException

    from app.config import settings
    from app.db import SessionLocal
    from app.models import OrgMembership, Organization, User
    from app.services import orgs as orgs_svc

    db = SessionLocal()
    try:
        db.add(Organization(id="org_x", name="X"))
        db.flush()
        db.add(OrgMembership(org_id="org_x", user_id="u1", role="owner"))
        db.commit()
        user = db.get(User, "u1")

        assert orgs_svc.require_may_found_org(db, user) is None  # hosted off → inert
        monkeypatch.setattr(settings, "hosted_mode", True)
        with pytest.raises(HTTPException):  # hosted on → gated
            orgs_svc.require_may_found_org(db, user)
    finally:
        db.close()


def test_first_org_is_free_second_is_refused(client, hosted):
    auth = _login(client, ADMIN_EMAIL)
    assert client.post("/api/orgs", json={"name": "First"}, headers=auth).status_code == 201
    r = client.post("/api/orgs", json={"name": "Second"}, headers=auth)
    assert r.status_code == 403
    assert "needs approval" in r.json()["detail"]


def test_org_member_cannot_found_their_own_without_approval(client, hosted):
    """Belonging to someone else's org counts — spawning a new tenant needs approval."""
    from app.services.email import outbox

    alex = _login(client, ADMIN_EMAIL)
    org = client.post("/api/orgs", json={"name": "Acme"}, headers=alex).json()
    outbox.clear()
    client.post(f"/api/orgs/{org['id']}/invites",
                json={"email": "dana@ascme-labs.com"}, headers=alex)
    token = outbox[0].text.rsplit("/invite/", 1)[1].split()[0]
    dana = _login(client, "dana@ascme-labs.com")
    client.post("/api/invites/accept", json={"token": token}, headers=dana)

    assert client.post("/api/orgs", json={"name": "Dana Co"}, headers=dana).status_code == 403


def test_enterprise_plan_grants_standing_multi_org(client, hosted, monkeypatch):
    _entitle(monkeypatch, "free")  # stand in for an enterprise licence
    auth = _login(client, ADMIN_EMAIL)
    for name in ("One", "Two", "Three"):
        assert client.post("/api/orgs", json={"name": name}, headers=auth).status_code == 201


# ---- request → approve → found ---------------------------------------------------
def test_request_approve_grants_exactly_one_more_org(client, operator):
    """The core loop, and the replay guard: an approval is spent once."""
    auth = operator
    client.post("/api/orgs", json={"name": "First"}, headers=auth)
    assert client.post("/api/orgs", json={"name": "Second"}, headers=auth).status_code == 403

    req = client.post("/api/orgs/requests",
                      json={"reason": "separate client workspace", "company": "Acme"},
                      headers=auth)
    assert req.status_code == 201
    assert req.json()["status"] == "pending"
    rid = req.json()["id"]

    assert client.post(f"/api/admin/org-requests/{rid}",
                       json={"approve": True}, headers=auth).json()["status"] == "approved"

    # Grant spends on the next org...
    assert client.post("/api/orgs", json={"name": "Second"}, headers=auth).status_code == 201
    # ...and cannot be replayed for a third.
    assert client.post("/api/orgs", json={"name": "Third"}, headers=auth).status_code == 403


def test_denied_request_grants_nothing(client, operator):
    auth = operator
    client.post("/api/orgs", json={"name": "First"}, headers=auth)
    rid = client.post("/api/orgs/requests", json={"reason": "please"}, headers=auth).json()["id"]
    assert client.post(f"/api/admin/org-requests/{rid}",
                       json={"approve": False, "note": "not in beta"}, headers=auth).json()["status"] == "denied"
    assert client.post("/api/orgs", json={"name": "Second"}, headers=auth).status_code == 403


def test_pending_request_alone_grants_nothing(client, operator):
    auth = operator
    client.post("/api/orgs", json={"name": "First"}, headers=auth)
    client.post("/api/orgs/requests", json={"reason": "please"}, headers=auth)
    assert client.post("/api/orgs", json={"name": "Second"}, headers=auth).status_code == 403


def test_request_refused_when_user_can_already_create(client, hosted):
    """A user with no org doesn't need to ask."""
    auth = _login(client, ADMIN_EMAIL)
    r = client.post("/api/orgs/requests", json={"reason": "x"}, headers=auth)
    assert r.status_code == 400
    assert "no request needed" in r.json()["detail"]


def test_resubmitting_updates_the_pending_request(client, operator):
    auth = operator
    client.post("/api/orgs", json={"name": "First"}, headers=auth)
    a = client.post("/api/orgs/requests", json={"reason": "first reason"}, headers=auth).json()
    b = client.post("/api/orgs/requests", json={"reason": "better reason"}, headers=auth).json()
    assert a["id"] == b["id"]  # updated, not duplicated
    assert b["reason"] == "better reason"
    assert len(client.get("/api/admin/org-requests", headers=auth).json()) == 1


def test_my_request_status_visible_to_requester(client, operator):
    auth = operator
    client.post("/api/orgs", json={"name": "First"}, headers=auth)
    client.post("/api/orgs/requests", json={"reason": "why not"}, headers=auth)
    mine = client.get("/api/orgs/requests/mine", headers=auth).json()
    assert mine["status"] == "pending" and mine["reason"] == "why not"


# ---- operator plane gating -------------------------------------------------------
def test_org_request_admin_endpoints_404_for_non_admin(client, hosted, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "platform_admin_emails", "")  # nobody is an operator
    auth = _login(client, ADMIN_EMAIL)
    assert client.get("/api/admin/org-requests", headers=auth).status_code == 404
    assert client.post("/api/admin/org-requests/oreq_x",
                       json={"approve": True}, headers=auth).status_code == 404


def test_non_admin_cannot_approve_own_request(client, hosted, monkeypatch):
    """A tenant can't self-approve — the decision endpoint is operator-only."""
    from app.config import settings

    monkeypatch.setattr(settings, "platform_admin_emails", ADMIN_EMAIL)
    dana = _login(client, "dana@ascme-labs.com")
    client.post("/api/orgs", json={"name": "Dana Co"}, headers=dana)
    rid = client.post("/api/orgs/requests", json={"reason": "mine"}, headers=dana).json()["id"]
    assert client.post(f"/api/admin/org-requests/{rid}",
                       json={"approve": True}, headers=dana).status_code == 404
    assert client.post("/api/orgs", json={"name": "Another"}, headers=dana).status_code == 403
