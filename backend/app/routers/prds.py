import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.providers import iter_reply
from app.schemas import (
    GrillApplyIn,
    GrillDeferIn,
    GrillApplyOut,
    GrillIn,
    PrdAiIn,
    PrdAiOut,
    PrdCreate,
    PrdLinkIn,
    PrdOut,
    PrdSummary,
    PrdUpdate,
    PrdVersionIn,
    PrdVersionOut,
)
from app.security import authz
from app.security.deps import get_current_user
from app.services import events as events_svc
from app.services import platform as platform_svc
from app.services import prds as prd_svc

router = APIRouter(prefix="/prds", tags=["prds"])


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _require_writable_prd(db: Session, user: User, prd_id: str) -> None:
    """Load-and-guard for PRD mutations: 404 unknown, 404/403 per membership."""
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    authz.require_writable(db, user.id, prd.project_id, "prd")


def _require_readable_prd(db: Session, user: User, prd_id: str):
    """Load-and-read-guard for PRD reads (tenant isolation, AL-70)."""
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    authz.require_readable(db, user.id, prd.project_id, "prd")
    return prd


@router.get("", response_model=list[PrdSummary])
def list_prds(project_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    authz.require_readable(db, user.id, project_id)
    return prd_svc.list_prds(db, project_id=project_id)


@router.post("", response_model=PrdOut, status_code=201)
def create_prd(body: PrdCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    authz.require_writable(db, user.id, body.project_id)
    return prd_svc.create_prd(
        db, title=body.title, template=body.template, project_id=body.project_id, body=body.body,
    )


@router.get("/{prd_id}/coverage")
def prd_coverage(prd_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prd = _require_readable_prd(db, user, prd_id)
    return prd_svc.coverage(db, prd)


@router.get("/{prd_id}/grill")
def prd_grill_state(prd_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The grill as the SERVER knows it (AL-296) — no client transcript involved.

    This is the endpoint that proves the item: before it, "has this PRD been grilled?"
    was only answerable by whoever happened to be holding the conversation."""
    prd = _require_readable_prd(db, user, prd_id)
    return prd_svc.grill_state(db, prd.id)


@router.post("/{prd_id}/grill/defer")
def prd_grill_defer(prd_id: str, body: GrillDeferIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Deliberately leave a dimension open (AL-298).

    Deferring is the author's decision, not the model's inference, so it gets an explicit
    route — and on a stub instance, which cannot detect a deferral in prose, it is the
    ONLY way to record one. `classify_grill` never downgrades it afterwards."""
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    authz.require_writable(db, user.id, prd.project_id, "prd")
    try:
        prd_svc.set_dimension(db, prd.id, body.dimension, "deferred", note=body.reason,
                              graded_by="author")
    except ValueError as e:
        raise HTTPException(422, str(e))
    events_svc.record_user(db, user, action="grill_defer", target_type="prd",
                           target_id=prd.id, project_id=prd.project_id,
                           meta={"dimension": body.dimension, "reason": body.reason})
    return prd_svc.grill_state(db, prd.id)


@router.post("/{prd_id}/decompose")
def decompose_prd(prd_id: str, create: bool = False, include_prose: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    if create:  # proposing tasks is a read; creating them is a write
        authz.require_writable(db, user.id, prd.project_id, "prd")
    return prd_svc.decompose(db, prd, create=create, include_prose=include_prose)


@router.get("/{prd_id}", response_model=PrdOut)
def get_prd(prd_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _require_readable_prd(db, user, prd_id)


@router.patch("/{prd_id}", response_model=PrdOut)
def update_prd(prd_id: str, body: PrdUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_writable_prd(db, user, prd_id)
    try:
        prd = prd_svc.update_prd(db, prd_id, **body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if prd is None:
        raise HTTPException(404, "prd not found")
    return prd


@router.get("/{prd_id}/versions", response_model=list[PrdVersionOut])
def list_versions(prd_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prd = _require_readable_prd(db, user, prd_id)
    return prd.versions


@router.post("/{prd_id}/versions", response_model=PrdOut, status_code=201)
def snapshot(prd_id: str, body: PrdVersionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_writable_prd(db, user, prd_id)
    prd = prd_svc.create_version(db, prd_id, note=body.note)
    if prd is None:
        raise HTTPException(404, "prd not found")
    return prd


@router.post("/{prd_id}/link", response_model=PrdOut)
def link(prd_id: str, body: PrdLinkIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_writable_prd(db, user, prd_id)
    prd = prd_svc.link_item(db, prd_id, body.item_id, add=body.add)
    if prd is None:
        raise HTTPException(404, "prd not found")
    return prd


@router.post("/{prd_id}/ai", response_model=PrdAiOut)
def ai(prd_id: str, body: PrdAiIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_writable_prd(db, user, prd_id)
    try:
        return PrdAiOut(text=prd_svc.ai_command(db, prd_id, body.command))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/{prd_id}/grill/stream")
def grill_stream(prd_id: str, body: GrillIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Interactive grill (AL-67): SSE `delta` events then `done`. Read-only — the
    proposed edits land via grill/apply → save. Light-context (PRD-grounded only)."""
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    authz.require_readable(db, user.id, prd.project_id, "prd")
    # Record the caller's side BEFORE generating (AL-296). The server owns the
    # conversation now, so an answer must survive a stream that dies mid-reply — losing
    # it would silently roll back progress toward approval.
    client_history = [m.model_dump() for m in body.history]
    if body.message:
        client_history = client_history + [{"role": "user", "text": body.message}]
    prd_svc.record_grill_turns(db, prd.id, client_history, via="human", actor=user.id)

    # Prefer what the server holds over what the caller sent: it is the same
    # conversation plus anything a second session contributed.
    history = prd_svc.grill_history(db, prd.id)
    context = prd_svc.grill_context(prd, history)
    question = body.message or "Begin — ask your opening clarifying questions about this PRD."

    # Resolve the project's provider eagerly, while the request DB session is open.
    provider, chat = platform_svc.resolve_chat(db, prd.project_id)

    def gen():
        # Accumulate the reply as it streams so the questions the grill ASKED are
        # recorded too — AL-297 has to classify what was put to the author, which it
        # cannot do from the answers alone. Same in-generator write the assistant
        # thread route already relies on.
        parts: list[str] = []
        if provider == "stub":
            # Offline: stream the deterministic opening questions.
            for line in prd_svc._stub_command("grill", prd).splitlines(keepends=True):
                parts.append(line)
                yield _sse("delta", json.dumps({"text": line}))
        else:
            for piece in iter_reply(chat, system=prd_svc.GRILL_CHAT_SYSTEM,
                                    context=context, question=question):
                parts.append(piece)
                yield _sse("delta", json.dumps({"text": piece}))
        reply = "".join(parts).strip()
        if reply:
            prd_svc.record_grill_turns(db, prd.id, history + [{"role": "agent", "text": reply}])
        # Grade the round (AL-298). Classification is a separate call from the streamed
        # conversation on purpose: the stream is for the author to read, this is the
        # state approval derives from, and a malformed token should not cost both.
        prd_svc.classify_grill(db, prd)
        yield _sse("done", "{}")

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{prd_id}/grill/apply", response_model=GrillApplyOut)
def grill_apply(prd_id: str, body: GrillApplyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Fold the grill transcript's decisions into a proposed PRD body AND preserve
    each decision as a candidate memory shard (AL-69). Returns the body + how many
    decisions were captured; the author reviews the shards in Memory Review and
    reviews/saves the body separately. Mutates → writable."""
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    authz.require_writable(db, user.id, prd.project_id, "prd")
    # Catch anything the stream missed — a client that grilled elsewhere, or a reply
    # that died before its turn was written. Appends only what isn't already stored.
    prd_svc.record_grill_turns(db, prd.id, [m.model_dump() for m in body.history],
                               via="human", actor=user.id)
    history = prd_svc.grill_history(db, prd.id)
    proposed = prd_svc.grill_apply(db, prd_id, history)
    shards = prd_svc.capture_grill_decisions(db, prd, history)
    prd_svc.classify_grill(db, prd)
    if shards:
        events_svc.record_user(db, user, action="grill_capture", target_type="prd",
                               target_id=prd.id, project_id=prd.project_id,
                               meta={"decisions": len(shards)})
    return GrillApplyOut(body=proposed, decisions_captured=len(shards))
