"""Feature/bug request (triage) service."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item, Request

REQUEST_TYPES = ["bug", "feature", "enhancement", "feedback"]


def next_request_id(db: Session) -> str:
    ids = db.scalars(select(Request.id)).all()
    nums = [int(m.group(1)) for i in ids if (m := re.match(r"R-(\d+)", i))]
    nxt = (max(nums) + 1) if nums else 1
    return f"R-{nxt}"


def list_requests(db: Session, project_id: str | None = None, type_: str | None = None) -> list[Request]:
    stmt = select(Request)
    if project_id:
        stmt = stmt.where(Request.project_id == project_id)
    if type_:
        stmt = stmt.where(Request.type == type_)
    return list(db.scalars(stmt.order_by(Request.created_at.desc())).all())


def create_request(
    db: Session,
    *,
    type_: str,
    title: str,
    detail: str = "",
    by: str = "",
    project_id: str = "core",
    ago: str = "just now",
    source_url: str = "",
    meta: dict | None = None,
) -> Request:
    if type_ not in REQUEST_TYPES:
        raise ValueError(f"invalid request type: {type_}")
    req = Request(
        id=next_request_id(db),
        project_id=project_id,
        type=type_,
        title=title,
        detail=detail,
        by=by,
        votes=0,
        status="new",
        ago=ago,
        source_url=source_url,
        meta=meta or {},
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def vote_request(db: Session, request_id: str, delta: int = 1) -> Request | None:
    req = db.get(Request, request_id)
    if req is None:
        return None
    req.votes = max(0, req.votes + delta)
    db.commit()
    db.refresh(req)
    return req


def link_request(db: Session, request_id: str, item_id: str | None) -> Request | None:
    req = db.get(Request, request_id)
    if req is None:
        return None
    if item_id:
        if db.get(Item, item_id) is None:
            raise ValueError(f"item not found: {item_id}")
        req.linked_to = item_id
        req.status = "linked"
    else:
        req.linked_to = None
        req.status = "new"
    db.commit()
    db.refresh(req)
    return req


def set_status(db: Session, request_id: str, status: str) -> Request | None:
    req = db.get(Request, request_id)
    if req is None:
        return None
    req.status = status
    db.commit()
    db.refresh(req)
    return req
