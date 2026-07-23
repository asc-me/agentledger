"""AL-74: the hosted-only organization gate.

In HOSTED_MODE a per-project Membership is not enough — the caller must also
belong to the project's org, so a project can never be reached from outside its
tenant. With HOSTED_MODE off (self-host) the org layer is completely inert.
"""
import pytest

from app.models import Membership, OrgMembership, Organization, Project
from app.security import authz


def _seed_two_orgs(db):
    """Two orgs, each with a project. alex (u1) has a per-project Membership on
    BOTH projects, but an org seat in org A only."""
    # Insert in FK dependency order (orgs → projects/memberships) so Postgres,
    # which enforces FKs, is satisfied.
    db.add_all([Organization(id="orgA", name="Org A"), Organization(id="orgB", name="Org B")])
    db.flush()
    db.add_all([
        Project(id="projA", name="Proj A", org_id="orgA"),
        Project(id="projB", name="Proj B", org_id="orgB"),
        Membership(user_id="u1", project_id="projA", access="write"),
        Membership(user_id="u1", project_id="projB", access="write"),
        OrgMembership(org_id="orgA", user_id="u1", role="owner"),
    ])
    db.commit()


@pytest.fixture()
def two_orgs(client):
    # `client` builds + seeds the schema; add org fixtures on top.
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        _seed_two_orgs(db)
    finally:
        db.close()


def test_hosted_mode_requires_org_membership(client, two_orgs, monkeypatch):
    from app.config import settings
    from app.db import SessionLocal

    monkeypatch.setattr(settings, "hosted_mode", True)
    db = SessionLocal()
    try:
        readable = authz.readable_project_ids(db, "u1")
        # In org A → sees projA; NOT in org B → projB is filtered out despite the
        # per-project Membership. Seeded NULL-org projects (core/web/infra) drop too.
        assert "projA" in readable
        assert "projB" not in readable
        assert "core" not in readable
    finally:
        db.close()


def test_self_host_ignores_org_layer(client, two_orgs):
    """HOSTED_MODE off: membership alone grants access; org_id is irrelevant."""
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        readable = authz.readable_project_ids(db, "u1")
        assert {"projA", "projB", "core"} <= set(readable)
    finally:
        db.close()


def test_hosted_rest_read_refused_cross_org(client, two_orgs, monkeypatch):
    """End-to-end: alex can read her own-org project but not the other org's,
    even though she holds a Membership row on it."""
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_mode", True)
    r = client.post("/api/auth/login", json={"email": "alex@ascme-labs.com", "password": "agentledger"})
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

    assert client.get("/api/items?project_id=projA", headers=auth).status_code == 200
    assert client.get("/api/items?project_id=projB", headers=auth).status_code == 404
