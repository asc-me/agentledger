import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.providers import get_chat_model, iter_reply
from app.schemas import (
    GrillApplyIn,
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
    history = [m.model_dump() for m in body.history]
    context = prd_svc.grill_context(prd, history)
    question = body.message or "Begin — ask your opening clarifying questions about this PRD."

    def gen():
        if settings.chat_provider == "stub":
            # Offline: stream the deterministic opening questions.
            for line in prd_svc._stub_command("grill", prd).splitlines(keepends=True):
                yield _sse("delta", json.dumps({"text": line}))
        else:
            for piece in iter_reply(get_chat_model(), system=prd_svc.GRILL_CHAT_SYSTEM,
                                    context=context, question=question):
                yield _sse("delta", json.dumps({"text": piece}))
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
    history = [m.model_dump() for m in body.history]
    proposed = prd_svc.grill_apply(db, prd_id, history)
    shards = prd_svc.capture_grill_decisions(db, prd, history)
    if shards:
        events_svc.record_user(db, user, action="grill_capture", target_type="prd",
                               target_id=prd.id, project_id=prd.project_id,
                               meta={"decisions": len(shards)})
    return GrillApplyOut(body=proposed, decisions_captured=len(shards))
