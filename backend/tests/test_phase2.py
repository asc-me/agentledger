"""Phase 2: public feedback intake + auto-duplicate detection (stub embedder)."""
import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.routers import public

    public._hits.clear()
    yield
    public._hits.clear()


def test_public_duplicates_no_auth(client):
    # Near-duplicate of seeded R-31 "Two-way GitHub issue sync".
    r = client.get("/api/public/duplicates", params={"q": "Two-way GitHub issue sync"})
    assert r.status_code == 200  # no Authorization header needed
    hits = r.json()
    assert any(h["kind"] == "request" and h["id"] == "R-31" for h in hits)
    assert hits[0]["score"] >= hits[-1]["score"]


def test_public_submit_creates_request_and_flags_duplicate(client, auth):
    r = client.post(
        "/api/public/requests",
        json={"type": "feature", "title": "Two-way GitHub issue sync please",
              "detail": "sync issues both directions", "email": "x@y.com"},
    )
    assert r.status_code == 201
    body = r.json()
    new_id = body["request"]["id"]
    assert body["request"]["by"] == "x@y.com"
    assert any(d["id"] == "R-31" for d in body["duplicates"])  # surfaced the existing one
    assert all(d["id"] != new_id for d in body["duplicates"])  # never itself

    # The new request shows up in the authenticated triage queue.
    reqs = client.get("/api/requests", headers=auth).json()
    assert any(x["id"] == new_id for x in reqs)


def test_public_submit_rejects_bad_type(client):
    r = client.post("/api/public/requests", json={"type": "banana", "title": "x"})
    assert r.status_code == 422


def test_public_rate_limit(client):
    codes = [
        client.get("/api/public/duplicates", params={"q": "spam"}).status_code
        for _ in range(25)
    ]
    assert 429 in codes  # sliding window trips after the cap
    assert codes.count(200) <= 20
