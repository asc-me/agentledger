"""Agent chat — retrieval-grounded, backed by the configured ChatModel provider.

The router assembles context (project state + top-k memory shards); the provider
turns it into a reply. The default stub provider composes a deterministic answer
offline; Ollama/Anthropic providers generate one.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.providers import get_chat_model, iter_reply
from app.schemas import ChatIn, ChatOut, ShardHit, ShardOut
from app.security.deps import get_current_user
from app.services import items as items_svc
from app.services import memory as mem_svc

router = APIRouter(prefix="/agent", tags=["agent"])

SYSTEM = (
    "You are AgentLedger's project agent. Answer using the supplied project state and "
    "memory shards. Be concise and cite item ids where relevant."
)


def _build_context(db: Session, project_id: str | None, hits) -> str:
    all_items = items_svc.list_items(db, project_id=project_id)
    by_status: dict[str, int] = {}
    for it in all_items:
        by_status[it.status] = by_status.get(it.status, 0) + 1
    parts = []
    summary = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(by_status.items()))
    parts.append(f"Project state: {summary or 'no items yet'}.")
    in_progress = [it for it in all_items if it.status == "in_progress"]
    if in_progress:
        parts.append("In progress: " + "; ".join(f"{it.id} {it.title}" for it in in_progress[:3]) + ".")
    nxt = items_svc.suggest_next(db, project_id=project_id)
    if nxt:
        parts.append(f"Suggested next: {nxt.id} — {nxt.title}.")
    if hits:
        parts.append("Relevant memory:")
        parts += [f"  · ({score:.2f}) {s.text}" for s, score in hits]
    else:
        parts.append("No matching memory shards found.")
    return "\n".join(parts)


@router.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    hits = mem_svc.search_memory(db, body.message, top_k=3, project_id=body.project_id)
    context = _build_context(db, body.project_id, hits)
    reply = get_chat_model().chat(system=SYSTEM, context=context, question=body.message)
    return ChatOut(
        reply=reply,
        shards=[ShardHit(shard=ShardOut.model_validate(s), score=round(sc, 4)) for s, sc in hits],
    )


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@router.post("/chat/stream")
def chat_stream(body: ChatIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Server-Sent Events: a `shards` event, then `delta` events, then `done` (F3)."""
    hits = mem_svc.search_memory(db, body.message, top_k=3, project_id=body.project_id)
    context = _build_context(db, body.project_id, hits)
    shards = [
        ShardHit(shard=ShardOut.model_validate(s), score=round(sc, 4)).model_dump(mode="json")
        for s, sc in hits
    ]

    def gen():
        yield _sse("shards", json.dumps(shards))
        for piece in iter_reply(get_chat_model(), system=SYSTEM, context=context, question=body.message):
            yield _sse("delta", json.dumps({"text": piece}))
        yield _sse("done", "{}")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
