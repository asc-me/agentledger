"""AL-73: BYOK provider API keys are encrypted at rest.

The key stored in platform_config.providers must be Fernet ciphertext (not the
raw key) when SECRET_ENCRYPTION_KEY is set; the UI still only ever sees a
`key_set` bool; the live provider layer transparently decrypts; and the
write-only round-trip (blank keeps the stored key) is preserved.
"""
import pytest

from app.security import secrets


@pytest.fixture()
def enc_key(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "secret_encryption_key", "unit-test-encryption-key")
    secrets._fernet.cache_clear()
    yield
    secrets._fernet.cache_clear()


# ---- the crypto primitive ----

def test_roundtrip_and_ciphertext_shape(enc_key):
    ct = secrets.encrypt("sk-live-abc123")
    assert ct.startswith("enc::")
    assert "sk-live-abc123" not in ct
    assert secrets.decrypt(ct) == "sk-live-abc123"


def test_legacy_plaintext_passes_through(enc_key):
    # A value stored before encryption (no prefix) is returned as-is.
    assert secrets.decrypt("sk-legacy-plain") == "sk-legacy-plain"


def test_noop_without_key(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "secret_encryption_key", "")
    assert secrets.encrypt("sk-x") == "sk-x"  # self-host default: store as-is


def test_empty_is_untouched(enc_key):
    assert secrets.encrypt("") == ""
    assert secrets.decrypt("") == ""


# ---- end-to-end through the platform config API ----

def test_provider_key_stored_encrypted_not_plaintext(client, auth, enc_key):
    raw = "sk-super-secret-BYOK-key"
    r = client.patch(
        "/api/platform?project_id=core",
        json={"active_chat_provider": "openai", "providers": {"openai": {"api_key": raw}}},
        headers=auth,
    )
    assert r.status_code == 200, r.text

    # The response redacts to key_set — never the raw key.
    pc = r.json()["provider_config"]["openai"]
    assert pc["key_set"] is True
    assert "api_key" not in pc

    # At rest, the stored value is ciphertext that decrypts back to the original.
    from app.models import PlatformConfig
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        stored = db.get(PlatformConfig, "core").providers["openai"]["api_key"]
    finally:
        db.close()
    assert stored.startswith("enc::")
    assert raw not in stored
    assert secrets.decrypt(stored) == raw


def test_blank_api_key_keeps_stored_key(client, auth, enc_key):
    raw = "sk-keepme"
    client.patch(
        "/api/platform?project_id=core",
        json={"active_chat_provider": "openai", "providers": {"openai": {"api_key": raw}}},
        headers=auth,
    )
    # A later update with a blank key (the redacted round-trip) must not wipe it.
    client.patch(
        "/api/platform?project_id=core",
        json={"providers": {"openai": {"api_key": "", "chat_model": "gpt-4o"}}},
        headers=auth,
    )
    from app.models import PlatformConfig
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        prov = db.get(PlatformConfig, "core").providers["openai"]
    finally:
        db.close()
    assert secrets.decrypt(prov["api_key"]) == raw
    assert prov["chat_model"] == "gpt-4o"
