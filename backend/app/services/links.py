"""Typed-link service (minimal — the Links graph UI lands in Phase 4)."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Link

LINK_TYPES = ["dependency", "code", "semantic", "tag"]


def create_link(
    db: Session, *, a: str, b: str, type_: str = "dependency", reason: str = "",
    confidence: float = 1.0, project_id: str = "core",
) -> Link:
    if type_ not in LINK_TYPES:
        raise ValueError(f"invalid link type: {type_}")
    link = Link(project_id=project_id, a=a, b=b, type=type_, reason=reason, confidence=confidence)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def delete_link(
    db: Session, *, a: str, b: str, type_: str | None = None, project_id: str | None = None,
) -> int:
    """Remove the directed (a, b) link(s) — the inverse of create_link. Omit `type_` to
    remove every link type for that pair; scope by `project_id` when given. Idempotent:
    returns the number of links removed (0 if the link never existed)."""
    stmt = delete(Link).where(Link.a == a, Link.b == b)
    if type_ is not None:
        stmt = stmt.where(Link.type == type_)
    if project_id is not None:
        stmt = stmt.where(Link.project_id == project_id)
    removed = db.execute(stmt).rowcount or 0
    db.commit()
    return removed


def list_links(db: Session, project_id: str | None = None) -> list[Link]:
    stmt = select(Link)
    if project_id:
        stmt = stmt.where(Link.project_id == project_id)
    return list(db.scalars(stmt).all())
