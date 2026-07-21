"""Dashboard aggregation (Phase 4) — one call powering all widgets."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Item, MemoryShard, Prd, Request
from app.services import mcp_stats
from app.services.items import STATUSES


def build(db: Session, project_id: str | None = None) -> dict:
    def item_q():
        q = select(Item)
        return q.where(Item.project_id == project_id) if project_id else q

    items = list(db.scalars(item_q()).all())
    by_status = {s: 0 for s in STATUSES}
    effort_total = 0
    for it in items:
        by_status[it.status] = by_status.get(it.status, 0) + 1
        effort_total += it.effort or 0

    requests = list(db.scalars(select(Request)).all())
    req_by_type: dict[str, int] = {}
    req_by_status: dict[str, int] = {}
    for r in requests:
        req_by_type[r.type] = req_by_type.get(r.type, 0) + 1
        req_by_status[r.status] = req_by_status.get(r.status, 0) + 1

    recent = sorted(items, key=lambda it: it.updated_at, reverse=True)[:6]

    return {
        "items_total": len(items),
        "items_by_status": by_status,
        "effort_total": effort_total,
        "done_count": by_status.get("done", 0),
        "in_progress_count": by_status.get("in_progress", 0),
        "blocked_count": by_status.get("blocked", 0),
        "requests_total": len(requests),
        "requests_by_type": req_by_type,
        "requests_by_status": req_by_status,
        "shard_count": db.scalar(select(func.count()).select_from(MemoryShard)) or 0,
        "prd_count": db.scalar(select(func.count()).select_from(Prd)) or 0,
        "mcp_calls": mcp_stats.total(db),
        "recent_items": [
            {"id": it.id, "title": it.title, "status": it.status, "date": it.date}
            for it in recent
        ],
    }
