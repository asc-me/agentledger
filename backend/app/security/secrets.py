"""Symmetric encryption for secrets stored at rest — BYOK provider keys (AL-73).

Values are Fernet tokens (AES-128-CBC + HMAC) tagged with an ``enc::`` prefix so
we can tell ciphertext from legacy plaintext and decrypt transparently:

- ``encrypt`` returns ``enc::<token>`` when ``SECRET_ENCRYPTION_KEY`` is set,
  else the plaintext unchanged (trusted single-tenant self-host default).
- ``decrypt`` reverses an ``enc::`` value and passes anything else through, so a
  DB that still holds pre-encryption plaintext keeps working; those rows become
  ciphertext the next time they're written.

The env secret can be any string; it's stretched to a 32-byte urlsafe-base64
Fernet key via SHA-256, so operators don't have to generate a Fernet key.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_PREFIX = "enc::"


@lru_cache(maxsize=4)
def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encryption_enabled() -> bool:
    return bool(settings.secret_encryption_key)


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage. No-op (returns input) when no key is configured
    or the value is empty — callers can encrypt unconditionally."""
    if not plaintext or not encryption_enabled():
        return plaintext
    token = _fernet(settings.secret_encryption_key).encrypt(plaintext.encode()).decode()
    return _PREFIX + token


def decrypt(stored: str) -> str:
    """Reverse ``encrypt``. Legacy plaintext (no prefix) passes through unchanged.
    A prefixed value that can't be decrypted (wrong/rotated key) returns "" rather
    than raising — a bad key must not 500 the request path."""
    if not stored or not stored.startswith(_PREFIX):
        return stored
    if not encryption_enabled():
        return ""
    try:
        return _fernet(settings.secret_encryption_key).decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        return ""
