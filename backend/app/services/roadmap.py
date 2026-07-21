"""Roadmap service — milestones grouped into phases with computed progress."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Milestone

PHASE_META = {
    "mvp": {"key": "mvp", "name": "MVP", "window": "2–4 weeks", "color": "#c6f24e"},
    "post": {"key": "post", "name": "Post-MVP", "window": "Q3 2026", "color": "#7ca2ff"},
    "later": {"key": "later", "name": "Later", "window": "exploring", "color": "#a78bfa"},
}
PHASE_ORDER = ["mvp", "post", "later"]


def list_roadmap(db: Session, project_id: str | None = None) -> list[dict]:
    stmt = select(Milestone)
    if project_id:
        stmt = stmt.where(Milestone.project_id == project_id)
    milestones = list(db.scalars(stmt.order_by(Milestone.sort_order.asc())).all())

    out = []
    for key in PHASE_ORDER:
        group = [m for m in milestones if m.phase == key]
        if not group:
            continue
        done = sum(1 for m in group if m.done)
        meta = PHASE_META[key]
        out.append({
            **meta,
            "done": done,
            "total": len(group),
            "milestones": [
                {"title": m.title, "tag": m.tag, "done": m.done} for m in group
            ],
        })
    return out
