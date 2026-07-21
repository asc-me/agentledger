"""Cross-cutting agent operations: explicit lesson extraction and progress digests."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.providers import get_extractor
from app.services import items as items_svc
from app.services import memory as memory_svc


def extract_lessons(db: Session, item_id: str) -> list[dict]:
    """Explicitly distill lessons from an item into memory shards (MCP extract_lessons)."""
    item = items_svc.get_item(db, item_id)
    if item is None:
        raise ValueError(f"item not found: {item_id}")
    lessons = get_extractor().extract(title=item.title, description=item.description)
    created = []
    for text in lessons:
        shard = memory_svc.add_memory(
            db, text_body=text, scope="item", source=f"lesson from {item.id}",
            item_id=item.id, project_id=item.project_id, fresh=True,
        )
        created.append({"id": shard.id, "text": shard.text})
    return created


def generate_digest(db: Session, project_id: str | None = None) -> str:
    """Compose a compact progress digest across the project (MCP generate_digest)."""
    all_items = items_svc.list_items(db, project_id=project_id)
    by_status: dict[str, int] = {}
    for it in all_items:
        by_status[it.status] = by_status.get(it.status, 0) + 1

    lines = ["# Progress digest", ""]
    lines.append("Status: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(by_status.items())))

    in_progress = [it for it in all_items if it.status == "in_progress"]
    if in_progress:
        lines += ["", "## In progress"] + [f"- {it.id} {it.title}" for it in in_progress]

    review = [it for it in all_items if it.status == "review"]
    if review:
        lines += ["", "## Awaiting review"] + [f"- {it.id} {it.title}" for it in review]

    blocked = [it for it in all_items if it.status == "blocked"]
    if blocked:
        lines += ["", "## Blocked"] + [f"- {it.id} {it.title} — {it.blocker}" for it in blocked]

    nxt = items_svc.suggest_next(db, project_id=project_id)
    if nxt:
        lines += ["", f"Suggested next: {nxt.id} — {nxt.title}"]
    return "\n".join(lines)
