"""Scoped API keys for agent / MCP authentication.

Keys look like `al_sk_<40 hex>`. Only the SHA-256 hash is stored; the plaintext
is shown to the user exactly once at creation.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid

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
) -> tuple[ApiKey, str]:
    """Create a key row and return (row, plaintext). Plaintext is not persisted.

    `project_id` scopes the key to one project (agent writes target it by default);
    None makes a global key.
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
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, raw


def verify_api_key(db: Session, raw: str) -> ApiKey | None:
    if not raw or not raw.startswith(KEY_PREFIX):
        return None
    row = db.query(ApiKey).filter(ApiKey.hashed_key == _hash_key(raw)).one_or_none()
    if row is not None:
        row.last_used = utcnow()
        db.commit()
    return row
