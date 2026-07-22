"""Idempotency for agent create calls.

An agent may retry a create after a timeout. If it passes the same
``idempotency_key``, we return the resource from the first call instead of making
a duplicate. Keys are global (they're random tokens the agent generates).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import IdempotencyKey


def lookup(db: Session, key: str) -> IdempotencyKey | None:
    if not key:
        return None
    return db.get(IdempotencyKey, key)


def remember(db: Session, key: str, tool: str, resource_id: str) -> None:
    if not key:
        return
    db.add(IdempotencyKey(key=key, tool=tool, resource_id=resource_id))
    db.commit()
