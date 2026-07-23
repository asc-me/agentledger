"""Scoped API keys for agent / MCP authentication.

Keys look like `al_sk_<40 hex>`. Only the SHA-256 hash is stored; the plaintext
is shown to the user exactly once at creation.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from app.models import ApiKey, utcnow

KEY_PREFIX = "al_sk_"


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key(
    db: Session,
    user_id: str,
    name: str,
    scopes: list[str] | None = None,
    project_id: str | None = None,
    expires_in_days: int | None = None,
) -> tuple[ApiKey, str]:
    """Create a key row and return (row, plaintext). Plaintext is not persisted.

    `project_id` scopes the key to one project (agent writes target it by default);
    None makes a global key. `expires_in_days` sets an optional lifetime; None =
    non-expiring.
    """
    raw = KEY_PREFIX + secrets.token_hex(20)
    row = ApiKey(
        id=str(uuid.uuid4()),
        user_id=user_id,
        project_id=project_id,
        name=name,
        prefix=raw[: len(KEY_PREFIX) + 4],
        hashed_key=_hash_key(raw),
        scopes=scopes or ["read", "write"],
        expires_at=utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, raw


def verify_api_key(db: Session, raw: str) -> ApiKey | None:
    if not raw or not raw.startswith(KEY_PREFIX):
        return None
    row = db.query(ApiKey).filter(ApiKey.hashed_key == _hash_key(raw)).one_or_none()
    if row is None:
        return None
    # Lifecycle gate (AL-72): a revoked or expired key authenticates no one.
    if row.revoked:
        return None
    if row.expires_at is not None:
        expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= utcnow():
            return None
    row.last_used = utcnow()
    db.commit()
    return row
