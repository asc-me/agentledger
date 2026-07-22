"""Item (tracker) service — shared by REST routers and the MCP server."""
from __future__ import annotations

import re
from datetime import timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models import Item, Project, utcnow

STATUSES = ["backlog", "next", "in_progress", "review", "done", "blocked"]
DEFAULT_LEASE_SECONDS = 600  # a claim with no heartbeat within this window is reclaimable


def next_item_id(db: Session, project_prefix: str = "AL") -> str:
    """Compute the next human item id, e.g. AL-23."""
    ids = db.scalars(select(Item.id)).all()
    nums = []
    for i in ids:
        m = re.match(rf"{project_prefix}-(\d+)", i)
        if m:
            nums.append(int(m.group(1)))
    nxt = (max(nums) + 1) if nums else 1
    return f"{project_prefix}-{nxt:02d}"


def list_items(db: Session, project_id: str | None = None, status: str | None = None) -> list[Item]:
    stmt = select(Item)
    if project_id:
        stmt = stmt.where(Item.project_id == project_id)
    if status:
        stmt = stmt.where(Item.status == status)
    stmt = stmt.order_by(Item.sort_order.asc(), Item.created_at.desc())
    return list(db.scalars(stmt).all())


def get_item(db: Session, item_id: str) -> Item | None:
    return db.get(Item, item_id)


def create_item(
    db: Session,
    *,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    effort: int = 0,
    status: str = "backlog",
    project_id: str = "core",
    reporter: dict | None = None,
    date: str = "",
) -> Item:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    if db.get(Project, project_id) is None:
        raise ValueError(f"unknown project: {project_id!r}")
    max_order = db.scalar(select(func.max(Item.sort_order))) or 0
    item = Item(
        id=next_item_id(db),
        project_id=project_id,
        title=title,
        description=description or "",
        tags=tags or [],
        effort=int(effort or 0),
        status=status,
        sort_order=max_order + 1,
        reporter=reporter or {},
        date=date,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_item(db: Session, item_id: str, **fields) -> Item | None:
    item = db.get(Item, item_id)
    if item is None:
        return None
    if "status" in fields and fields["status"] is not None:
        if fields["status"] not in STATUSES:
            raise ValueError(f"invalid status: {fields['status']}")
    prev_status = item.status
    for key in ("title", "description", "status", "tags", "effort", "blocker", "pr", "date",
                "github_url", "assignee"):
        if key in fields and fields[key] is not None:
            setattr(item, key, fields[key])
    db.commit()
    db.refresh(item)

    if item.status == "done" and prev_status != "done":
        _auto_extract_lessons(db, item)
    return item


def _auto_extract_lessons(db: Session, item: Item) -> None:
    """On completion, distill lessons into memory shards (respects project.auto_extract)."""
    from app.models import Project
    from app.services import memory as memory_svc

    project = db.get(Project, item.project_id)
    if project is not None and not project.auto_extract:
        return
    # Skip if we've already extracted for this item.
    existing = [s for s in memory_svc.list_shards(db, project_id=item.project_id)
                if s.source == f"lesson from {item.id}"]
    if existing:
        return
    from app.providers import get_extractor

    try:
        lessons = get_extractor().extract(title=item.title, description=item.description)
    except Exception:
        return  # never let extraction failure block a status change
    for text in lessons:
        memory_svc.add_memory(
            db, text_body=text, scope="item", source=f"lesson from {item.id}",
            item_id=item.id, project_id=item.project_id, fresh=True,
        )


def reorder_items(db: Session, ordered_ids: list[str]) -> list[Item]:
    """Persist a new drag order. `ordered_ids` is the full desired top→bottom order."""
    for idx, iid in enumerate(ordered_ids):
        item = db.get(Item, iid)
        if item is not None:
            item.sort_order = idx
    db.commit()
    return list_items(db)


def search_items(
    db: Session,
    query: str = "",
    status: str | None = None,
    limit: int = 25,
    project_id: str | None = None,
    tags: list[str] | None = None,
) -> list[Item]:
    # Status/project are simple column filters (SQL); the free-text query and tag
    # matching run in Python so `query` can match a tag too and stay dialect-agnostic
    # (tags is a JSON column). The result set here is small.
    stmt = select(Item)
    if project_id:
        stmt = stmt.where(Item.project_id == project_id)
    if status:
        stmt = stmt.where(Item.status == status)
    rows = list(db.scalars(stmt.order_by(Item.sort_order.asc())).all())

    q = query.lower().strip()
    want_tags = {t.lower() for t in (tags or [])}

    def matches(it: Item) -> bool:
        item_tags = {t.lower() for t in (it.tags or [])}
        if want_tags and not (want_tags & item_tags):
            return False
        if q and q not in it.title.lower() and q not in (it.description or "").lower() and not any(
            q in t for t in item_tags
        ):
            return False
        return True

    return [it for it in rows if matches(it)][:limit]


def get_backlog(db: Session, limit: int = 20, project_id: str | None = None) -> list[Item]:
    stmt = select(Item).where(Item.status.in_(["backlog", "next"]))
    if project_id:
        stmt = stmt.where(Item.project_id == project_id)
    stmt = stmt.order_by(Item.sort_order.asc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_item_details(db: Session, item_id: str) -> dict | None:
    from app.models import MemoryShard, Request

    item = db.get(Item, item_id)
    if item is None:
        return None
    shards = db.scalars(select(MemoryShard).where(MemoryShard.item_id == item_id)).all()
    reqs = db.scalars(select(Request).where(Request.linked_to == item_id)).all()
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "tags": item.tags,
        "effort": item.effort,
        "blocker": item.blocker,
        "pr": item.pr,
        "linked_shards": [{"id": s.id, "text": s.text, "source": s.source} for s in shards],
        "linked_requests": [{"id": r.id, "title": r.title, "type": r.type} for r in reqs],
    }


def suggest_next(db: Session, project_id: str | None = None) -> Item | None:
    """Rank the best next item: prefer `next`, then `backlog`; skip blocked; lowest effort first."""
    candidates = [
        it for it in list_items(db, project_id=project_id)
        if it.status in ("next", "backlog") and not it.blocker
    ]
    if not candidates:
        return None
    rank = {"next": 0, "backlog": 1}
    candidates.sort(key=lambda it: (rank.get(it.status, 9), it.effort or 99, it.sort_order))
    return candidates[0]


# ---- Assignment / agent claiming (feature A) ----

def _aware(dt):
    """SQLite hands datetimes back naive; treat a naive value as UTC for comparisons."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_claimable(it: Item, cutoff) -> bool:
    """An item is claimable if it isn't blocked and is either fresh unclaimed backlog/next,
    or work with a stale (abandoned) lease."""
    if it.blocker:
        return False
    stale = it.claimed_by is not None and it.claimed_at is not None and _aware(it.claimed_at) < cutoff
    if stale:
        return it.status in ("next", "backlog", "in_progress")
    if it.claimed_by is None:
        return it.status in ("next", "backlog")
    return False  # someone holds a live lease


def _ready_candidates(db: Session, project_id: str | None, lease_seconds: int) -> list[Item]:
    cutoff = utcnow() - timedelta(seconds=lease_seconds)
    out = [it for it in list_items(db, project_id=project_id) if _is_claimable(it, cutoff)]
    # Prefer next, then resuming abandoned in-progress work, then backlog; lowest effort first.
    rank = {"next": 0, "in_progress": 1, "backlog": 2}
    out.sort(key=lambda it: (rank.get(it.status, 9), it.effort or 99, it.sort_order))
    return out


def claim_next(
    db: Session, agent_id: str, project_id: str | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS
) -> Item | None:
    """Atomically assign the best ready item to `agent_id` and move it to in_progress.

    Concurrency-safe: the UPDATE guard means only one caller wins a given row, so two agents
    never claim the same item. Returns the claimed item, or None if nothing is ready.
    """
    now = utcnow()
    for cand in _ready_candidates(db, project_id, lease_seconds):
        # Optimistic-concurrency guard: only win the row if `claimed_by` is still what we read
        # (None for a fresh item, the stale holder for a reclaim). Dialect-safe — no time math in SQL.
        stmt = update(Item).where(Item.id == cand.id)
        stmt = (
            stmt.where(Item.claimed_by.is_(None))
            if cand.claimed_by is None
            else stmt.where(Item.claimed_by == cand.claimed_by)
        )
        stmt = stmt.values(claimed_by=agent_id, claimed_at=now, assignee=agent_id, status="in_progress")
        result = db.execute(stmt)
        db.commit()
        if result.rowcount == 1:
            db.expire_all()
            return db.get(Item, cand.id)
        # Lost the race for this candidate — try the next.
    return None


def heartbeat(db: Session, item_id: str, agent_id: str) -> Item | None:
    """Extend the lease on a claimed item. Returns the item, or None if the agent isn't the holder."""
    item = db.get(Item, item_id)
    if item is None or item.claimed_by != agent_id:
        return None
    item.claimed_at = utcnow()
    db.commit()
    db.refresh(item)
    return item


def release_item(db: Session, item_id: str, agent_id: str, to_status: str = "next") -> Item | None:
    """Give a claimed item back to the queue. Returns the item, or None if not the holder."""
    item = db.get(Item, item_id)
    if item is None or item.claimed_by != agent_id:
        return None
    item.claimed_by = None
    item.claimed_at = None
    item.assignee = ""
    if item.status == "in_progress" and to_status in STATUSES:
        item.status = to_status
    db.commit()
    db.refresh(item)
    return item
