"""AL-73: public endpoints are opt-in per project and addressed by share token.

Before this, /public/roadmap, /duplicates, /widget-config and /requests accepted
an arbitrary project_id unauthenticated → cross-tenant read/write. Now a project
is reachable publicly ONLY when it opts in, and (in hosted mode) ONLY via its
unguessable share token — never a named project_id.
"""
SEEDED_TOKEN = "demo-core-roadmap"  # seed.py opts `core` into public sharing


def _auth(client, email="alex@ascme-labs.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---- reads are gated by opt-in ----

def test_opted_in_project_roadmap_is_public(client):
    # core is seeded public — reachable by id (self-host) and by token.
    assert client.get("/api/public/roadmap?project_id=core").status_code == 200
    assert client.get(f"/api/public/roadmap?token={SEEDED_TOKEN}").status_code == 200


def test_non_opted_project_is_not_public(client):
    # `web` never opted in → its roadmap/duplicates/widget-config are all 404,
    # whether named directly or not, so it can't be read cross-tenant.
    assert client.get("/api/public/roadmap?project_id=web").status_code == 404
    assert client.get("/api/public/widget-config?project_id=web").status_code == 404
    assert client.get("/api/public/duplicates", params={"q": "x", "project_id": "web"}).status_code == 404


def test_unknown_token_is_404(client):
    assert client.get("/api/public/roadmap?token=not-a-real-token").status_code == 404


def test_hosted_mode_hides_all_projects_behind_tokens(client, monkeypatch):
    # In hosted mode there is no project_id path at all: a private project, a public
    # one, and a nonexistent id are indistinguishable by raw id (all 404) — the only
    # way in is a valid share token, so tenant existence can't be probed.
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_mode", True)
    for pid in ("web", "core", "ghost"):
        assert client.get(f"/api/public/roadmap?project_id={pid}").status_code == 404


# ---- hosted mode: token only, never a raw project_id ----

def test_hosted_mode_requires_token(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_mode", True)
    # Even the opted-in project can't be reached by raw id in hosted mode…
    assert client.get("/api/public/roadmap?project_id=core").status_code == 404
    # …only by its share token.
    assert client.get(f"/api/public/roadmap?token={SEEDED_TOKEN}").status_code == 200


# ---- opt-in flow mints a token ----

def test_enabling_public_share_mints_token(client):
    auth = _auth(client)
    # web starts private.
    before = client.get("/api/platform?project_id=web", headers=auth).json()
    assert before["public_share_enabled"] is False
    assert not before["share_token"]

    up = client.patch("/api/platform?project_id=web", json={"public_share_enabled": True}, headers=auth)
    assert up.status_code == 200
    token = up.json()["share_token"]
    assert token, "enabling public share should mint a token"

    # Now web's roadmap is reachable by that token.
    assert client.get(f"/api/public/roadmap?token={token}").status_code == 200


# ---- public submit is gated too ----

def test_public_submit_refused_for_non_opted_project(client):
    r = client.post("/api/public/requests", json={"type": "bug", "title": "hi", "project_id": "web"})
    assert r.status_code == 404


def test_public_submit_allowed_for_opted_in_project(client):
    r = client.post("/api/public/requests", json={"type": "bug", "title": "hi", "project_id": "core"})
    assert r.status_code == 201, r.text
