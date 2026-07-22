"""Phase 2: public feedback intake + auto-duplicate detection (stub embedder)."""


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


def test_public_submit_captures_context(client, auth):
    r = client.post(
        "/api/public/requests",
        json={"type": "bug", "title": "Checkout button dead on mobile",
              "detail": "Tapping Pay does nothing on iOS Safari.",
              "source_url": "https://shop.example.com/checkout",
              "meta": {"app_version": "2.4.1"}},
        headers={"User-Agent": "TestBrowser/9.9"},
    )
    assert r.status_code == 201
    new_id = r.json()["request"]["id"]
    got = next(x for x in client.get("/api/requests", headers=auth).json() if x["id"] == new_id)
    assert got["detail"] == "Tapping Pay does nothing on iOS Safari."  # detail is now persisted
    assert got["source_url"] == "https://shop.example.com/checkout"    # page captured
    assert got["meta"]["app_version"] == "2.4.1"                       # custom meta kept
    assert got["meta"]["user_agent"] == "TestBrowser/9.9"              # UA captured server-side


_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


def test_attachment_upload_link_and_serve(client, auth):
    up = client.post(
        "/api/public/attachments",
        files={"file": ("shot.png", _PNG_1x1, "image/png")},
    )
    assert up.status_code == 201, up.text
    att_id = up.json()["id"]

    # Attach it to a submission, then read it back through triage.
    sub = client.post(
        "/api/public/requests",
        json={"type": "bug", "title": "Broken layout with screenshot", "attachment_ids": [att_id]},
    )
    assert sub.status_code == 201
    new_id = sub.json()["request"]["id"]
    got = next(x for x in client.get("/api/requests", headers=auth).json() if x["id"] == new_id)
    assert got["attachment_ids"] == [att_id]

    served = client.get(f"/api/public/attachments/{att_id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == _PNG_1x1


def test_attachment_rejects_non_image(client):
    r = client.post(
        "/api/public/attachments",
        files={"file": ("evil.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 422


def test_honeypot_rejects_bot(client):
    r = client.post(
        "/api/public/requests",
        json={"type": "feedback", "title": "spammy", "hp": "http://spam.example"},
    )
    assert r.status_code == 400


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
