"""Assistant conversation threads (AL-174).

Persistence for in-app AI assistant conversations scoped to an item or PRD, plus the
context-assembly that grounds each turn in the entity + its linked memory. The
tool-calling loop (AL-172), the SSE surface + endpoints (AL-175), and the approve/apply
flow (AL-177) build on this — here we only store the conversation and assemble grounding.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AssistantMessage, AssistantThread, Item, Prd, utcnow

ENTITY_TYPES = ("item", "prd")
_CONTEXT_BUDGET = 6000  # chars — a stand-in token budget; trims oversized entity bodies


def create_thread(
    db: Session,
    *,
    project_id: str,
    entity_type: str,
    entity_id: str,
    provider: str = "",
    model: str = "",
    title: str = "",
) -> AssistantThread:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of {ENTITY_TYPES}: {entity_type!r}")
    thread = AssistantThread(
        id="th_" + uuid.uuid4().hex[:12],
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        provider=provider,
        model=model,
        title=title,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def get_thread(db: Session, thread_id: str) -> AssistantThread | None:
    return db.get(AssistantThread, thread_id)


def set_thread_model(db: Session, thread_id: str, *, provider: str, model: str = "") -> AssistantThread | None:
    """Pick the provider/model that drives a thread (AL-176 model picker)."""
    thread = db.get(AssistantThread, thread_id)
    if thread is None:
        return None
    thread.provider = provider
    thread.model = model
    thread.updated_at = utcnow()
    db.commit()
    db.refresh(thread)
    return thread


def list_threads(
    db: Session, *, project_id: str, entity_type: str | None = None, entity_id: str | None = None
) -> list[AssistantThread]:
    """Threads in a project, most-recently-active first; optionally scoped to one entity."""
    stmt = select(AssistantThread).where(AssistantThread.project_id == project_id)
    if entity_type is not None:
        stmt = stmt.where(AssistantThread.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AssistantThread.entity_id == entity_id)
    stmt = stmt.order_by(AssistantThread.updated_at.desc())
    return list(db.scalars(stmt).all())


def add_message(
    db: Session,
    thread_id: str,
    *,
    role: str,
    content: str = "",
    tool_calls: list | None = None,
    tool_results: list | None = None,
    proposed_actions: list | None = None,
) -> AssistantMessage | None:
    """Append a turn, assigning the next `seq` within the thread and bumping the thread's
    `updated_at` so list ordering reflects recent activity."""
    thread = db.get(AssistantThread, thread_id)
    if thread is None:
        return None
    next_seq = db.scalar(
        select(func.coalesce(func.max(AssistantMessage.seq), -1)).where(
            AssistantMessage.thread_id == thread_id
        )
    ) + 1
    msg = AssistantMessage(
        id="msg_" + uuid.uuid4().hex[:12],
        thread_id=thread_id,
        seq=next_seq,
        role=role,
        content=content,
        tool_calls=tool_calls or [],
        tool_results=tool_results or [],
        proposed_actions=proposed_actions or [],
    )
    db.add(msg)
    thread.updated_at = utcnow()  # touch so the thread sorts to the top of list_threads
    db.commit()
    db.refresh(msg)
    return msg


def thread_context(db: Session, thread: AssistantThread) -> str:
    """Grounding for the assistant: the thread's entity (PRD body or item detail) plus its
    linked memory, trimmed to a budget. The tool-calling loop prepends this as context;
    AL-175 can extend it with linked code."""
    if thread.entity_type == "prd":
        prd = db.get(Prd, thread.entity_id)
        if prd is None:
            return f"(PRD {thread.entity_id} not found)"
        body = _trim(prd.body or "(empty)")
        return f"PRD — {prd.title} ({prd.status}):\n{body}"

    item = db.get(Item, thread.entity_id)
    if item is None:
        return f"(item {thread.entity_id} not found)"
    parts = [f"Item {item.id} — {item.title} ({item.status})"]
    if item.description:
        parts.append(_trim(item.description))
    if item.touchpoints:
        parts.append("Touchpoints: " + ", ".join(item.touchpoints))
    linked = _linked_memory(db, item.project_id, item.id)
    if linked:
        parts.append("Linked memory:\n" + "\n".join(f"- {t}" for t in linked))
    return "\n".join(parts)


def _linked_memory(db: Session, project_id: str, item_id: str, limit: int = 5) -> list[str]:
    from app.services import memory as mem_svc

    shards = [s for s in mem_svc.list_shards(db, project_id=project_id) if s.item_id == item_id]
    return [s.text for s in shards[:limit]]


def _trim(text: str) -> str:
    if len(text) <= _CONTEXT_BUDGET:
        return text
    return text[:_CONTEXT_BUDGET].rstrip() + "\n…(truncated)"
