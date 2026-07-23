"""AL-72: auth hardening — password strength, login brute-force, registration
gate + non-enumeration, and API-key lifecycle (expiry + revoke)."""
from datetime import timedelta

import pytest

from app.models import ApiKey, utcnow


def _register_body(**over):
    body = {"name": "New User", "email": "new@example.com", "handle": "newbie", "password": "s3cure-pass"}
    body.update(over)
    return body


# ---- password strength ----

@pytest.mark.parametrize("pw", ["short", "aaaaaaaa", " leadingspace123"])
def test_register_rejects_weak_password(client, pw):
    r = client.post("/api/auth/register", json=_register_body(password=pw))
    assert r.status_code == 422, f"{pw!r} should be rejected"


def test_register_accepts_strong_password(client):
    r = client.post("/api/auth/register", json=_register_body(password="c0rrect-horse"))
    assert r.status_code == 201, r.text


# ---- registration gate + non-enumeration ----

def test_registration_can_be_closed(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "open_registration", False)
    r = client.post("/api/auth/register", json=_register_body())
    assert r.status_code == 403


def test_duplicate_register_is_generic(client):
    # alex@ascme-labs.com is seeded. The 409 must not disclose email-vs-handle.
    r = client.post("/api/auth/register", json=_register_body(email="alex@ascme-labs.com", handle="fresh"))
    assert r.status_code == 409
    assert "email" not in r.text.lower() and "handle" not in r.text.lower()


# ---- login brute-force ----

def test_login_brute_force_is_rate_limited(client):
    from app.config import settings

    # Exhaust the per-email allowance with wrong-password attempts → eventually 429.
    saw_429 = False
    for _ in range(settings.login_rate_per_min + 3):
        r = client.post("/api/auth/login", json={"email": "alex@ascme-labs.com", "password": "wrong"})
        if r.status_code == 429:
            saw_429 = True
            break
        assert r.status_code == 401
    assert saw_429, "brute-force attempts were never throttled"


# ---- API-key lifecycle ----

def _mint(client, auth, **body):
    r = client.post("/api/api-keys", json={"name": "t", **body}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _call_ok(client, key: str) -> int:
    r = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "search_items", "arguments": {"query": ""}}},
        headers={"X-API-Key": key},
    )
    return r.status_code


def test_key_with_expiry_is_reported(client, auth):
    created = _mint(client, auth, expires_in_days=30)
    assert created["expires_at"] is not None
    assert created["revoked"] is False
    # A fresh, unexpired key authenticates fine.
    assert _call_ok(client, created["plaintext"]) == 200


def test_expired_key_is_rejected(client, auth):
    created = _mint(client, auth, expires_in_days=30)
    # Backdate its expiry directly, then it must stop authenticating.
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(ApiKey, created["id"])
        row.expires_at = utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()
    assert _call_ok(client, created["plaintext"]) == 401


def test_revoked_key_is_rejected(client, auth):
    created = _mint(client, auth)
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(ApiKey, created["id"])
        row.revoked = True
        db.commit()
    finally:
        db.close()
    assert _call_ok(client, created["plaintext"]) == 401
