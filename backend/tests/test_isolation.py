"""Phase 6 (AL-70): cross-tenant read isolation is enforced, not just displayed.

Every project-scoped READ endpoint must refuse a project the caller can't read —
and refuse it with a 404 so a non-member can't even probe whether the project
exists. Seeded memberships (seed.py): alex = write core/web/infra; ops = read
core, write infra, NONE on web; kate = read core/web. All seeded content
(items, requests, shards, PRDs, links) lives in `core`.

Runs on both SQLite and Postgres via the two-engine CI gate.
"""
import uuid

import pytest


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _register(client):
    """A brand-new tenant: a real account with zero project memberships."""
    handle = "stranger_" + uuid.uuid4().hex[:6]
    r = client.post(
        "/api/auth/register",
        json={"name": "Stranger", "email": f"{handle}@example.com",
              "handle": handle, "password": "agentledger"},
    )
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# Project-scoped GET reads that take ?project_id and must be gated.
READ_GETS = [
    "/api/items",
    "/api/requests",
    "/api/prds",
    "/api/dashboard",
    "/api/roadmap",
    "/api/links",
    "/api/memory/shards",
    "/api/memory/candidates",
    "/api/memory/candidate-clusters",
    "/api/memory/export",
]

# Reads addressed by a core-owned resource id (not a project_id query).
PRD_BY_ID = [
    "/api/prds/PRD-1",
    "/api/prds/PRD-1/coverage",
    "/api/prds/PRD-1/versions",
]


@pytest.mark.parametrize("path", READ_GETS)
def test_non_member_cannot_read_foreign_project(client, path):
    """ops has no membership on `web` → every scoped read of web 404s."""
    ops = _login(client, "ops@ascme-labs.com")
    r = client.get(f"{path}?project_id=web", headers=ops)
    assert r.status_code == 404, f"{path} leaked web to a non-member: {r.status_code}"


@pytest.mark.parametrize("path", READ_GETS)
def test_member_can_read_own_project(client, path):
    """The gate must not over-block: ops reads `core` (read membership) fine."""
    ops = _login(client, "ops@ascme-labs.com")
    r = client.get(f"{path}?project_id=core", headers=ops)
    assert r.status_code == 200, f"{path} wrongly denied a reader: {r.status_code} {r.text}"


@pytest.mark.parametrize("path", READ_GETS)
def test_existence_hiding_forbidden_and_missing_are_indistinguishable(client, path):
    """A non-member must not tell a real-but-forbidden project (`web`) apart from a
    nonexistent one (`ghost`): both 404 with the same shape."""
    ops = _login(client, "ops@ascme-labs.com")
    forbidden = client.get(f"{path}?project_id=web", headers=ops)
    missing = client.get(f"{path}?project_id=ghost-does-not-exist", headers=ops)
    assert forbidden.status_code == missing.status_code == 404


def test_fresh_tenant_sees_nothing(client):
    """A newly-registered account with zero memberships can read no project's data
    — including core-owned resources addressed directly by id."""
    stranger = _register(client)
    for path in READ_GETS:
        r = client.get(f"{path}?project_id=core", headers=stranger)
        assert r.status_code == 404, f"{path} leaked core to a fresh tenant"
    for path in PRD_BY_ID:
        r = client.get(path, headers=stranger)
        assert r.status_code == 404, f"{path} leaked a core PRD to a fresh tenant"
    r = client.post(
        "/api/memory/search",
        json={"query": "anything", "top_k": 5, "project_id": "core"},
        headers=stranger,
    )
    assert r.status_code == 404


def test_memory_search_refuses_foreign_project(client):
    """POST /memory/search carries project_id in the body — same gate applies."""
    ops = _login(client, "ops@ascme-labs.com")
    r = client.post(
        "/api/memory/search",
        json={"query": "postgres", "top_k": 5, "project_id": "web"},
        headers=ops,
    )
    assert r.status_code == 404


def test_prd_by_id_refused_cross_tenant(client):
    """A core PRD read by id must 404 for a non-core member (fresh tenant), and
    resolve for a core reader (ops) — proving the id path is gated, not just list."""
    stranger = _register(client)
    ops = _login(client, "ops@ascme-labs.com")
    for path in PRD_BY_ID:
        assert client.get(path, headers=stranger).status_code == 404
        assert client.get(path, headers=ops).status_code == 200
