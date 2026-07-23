"""The audit ledger (AL-43): one owner for recording and reading mutation events.

Written at the boundaries — the MCP dispatcher for agent (API-key) actions and
REST routers for user actions — so every accepted mutation captures who did it.
Recording never raises into the caller: an audit failure must not fail the
operation it audits (best-effort, logged).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiKey, Event, User

logger = logging.getLogger("agentledger.events")


def record(
    db: Session,
    *,
    actor_type: str,
    actor_id: str = "",
    actor_label: str = "",
    surface: str,
    action: str,
    target_type: str = "",
    target_id: str = "",
    project_id: str | None = None,
    meta: dict | None = None,
) -> None:
    try:
        db.add(Event(
            actor_type=actor_type, actor_id=actor_id, actor_label=actor_label,
            surface=surface, action=action, target_type=target_type,
            target_id=target_id, project_id=project_id, meta=meta,
        ))
        db.commit()
    except Exception:  # noqa: BLE001 — auditing must never break the audited op
        logger.exception("failed to record event %r", action)
        db.rollback()


def record_key(db: Session, key: ApiKey, *, action: str, target_type: str = "",
               target_id: str = "", project_id: str | None = None, meta: dict | None = None) -> None:
    """Record an agent action, attributed to the API key that performed it."""
    record(
        db, actor_type="apikey", actor_id=key.id, actor_label=key.name or key.id,
        surface="mcp", action=action, target_type=target_type, target_id=target_id,
        project_id=project_id, meta=meta,
    )


def record_user(db: Session, user: User, *, action: str, target_type: str = "",
                target_id: str = "", project_id: str | None = None, meta: dict | None = None) -> None:
    """Record a user action from a REST route, attributed to the logged-in user."""
    record(
        db, actor_type="user", actor_id=user.id, actor_label=user.handle or user.name,
        surface="rest", action=action, target_type=target_type, target_id=target_id,
        project_id=project_id, meta=meta,
    )


def list_events(db: Session, *, project_ids: list[str], limit: int = 50, offset: int = 0,
                action: str | None = None) -> dict:
    """Most-recent-first events across the projects the caller may read. Includes
    project-less events (e.g. global memory) only implicitly via NULL — callers
    pass their readable project set."""
    stmt = select(Event).where(Event.project_id.in_(project_ids))
    if action:
        stmt = stmt.where(Event.action == action)
    stmt = stmt.order_by(Event.id.desc())
    total = len(db.scalars(select(Event.id).where(Event.project_id.in_(project_ids))).all())
    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    return {
        "results": [_event_dict(e) for e in rows],
        "total": total, "limit": limit, "offset": offset,
        "has_more": offset + limit < total,
    }


def _event_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "ts": e.ts.isoformat() if e.ts else None,
        "actor_type": e.actor_type,
        "actor_id": e.actor_id,
        "actor_label": e.actor_label,
        "surface": e.surface,
        "action": e.action,
        "target_type": e.target_type,
        "target_id": e.target_id,
        "project_id": e.project_id,
        "meta": e.meta,
    }
