from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MemoryShard, User
from app.schemas import MemorySearchIn, ShardCreate, ShardHit, ShardOut
from app.security import authz
from app.security.deps import get_current_user
from app.services import events as events_svc
from app.services import memory as mem_svc

router = APIRouter(prefix="/memory", tags=["memory"])


class ShardEdit(BaseModel):
    text: str


class ImportIn(BaseModel):
    shards: list[dict]
    project_id: str = "core"


@router.get("/shards", response_model=list[ShardOut])
def list_shards(
    project_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return mem_svc.list_shards(db, project_id=project_id, status=status)


@router.get("/candidates", response_model=list[ShardOut])
def list_candidates(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """The review queue (AL-49): agent-written shards awaiting human publish."""
    return mem_svc.list_shards(db, project_id=project_id, status="candidate")


@router.post("/shards", response_model=ShardOut, status_code=201)
def add_shard(body: ShardCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.project_id is not None:
        authz.require_writable(db, user.id, body.project_id)
    elif not authz.writable_project_ids(db, user.id):
        # A global (project-less) shard still requires write access somewhere.
        raise HTTPException(403, "no write access to any project")
    # A human wrote it → published straight away (the trust boundary is for agents).
    return mem_svc.add_memory(
        db,
        text_body=body.text,
        scope=body.scope,
        item_id=body.item_id,
        project_id=body.project_id,
        status="published",
        origin=f"user:{user.handle or user.id}",
    )


def _review_shard(shard_id: str, to_status: str, action: str, db: Session, user: User) -> MemoryShard:
    existing = db.get(MemoryShard, shard_id)
    if existing is None:
        raise HTTPException(404, "shard not found")
    if existing.project_id is not None:
        authz.require_writable(db, user.id, existing.project_id, "shard")
    elif not authz.writable_project_ids(db, user.id):
        raise HTTPException(403, "no write access to any project")
    shard = mem_svc.set_status(db, shard_id, to_status)
    events_svc.record_user(db, user, action=action, target_type="shard",
                           target_id=shard_id, project_id=existing.project_id)
    return shard


@router.post("/shards/{shard_id}/publish", response_model=ShardOut)
def publish_shard(shard_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Promote a candidate into the trusted retrieval path (AL-49)."""
    return _review_shard(shard_id, "published", "publish_shard", db, user)


@router.post("/shards/{shard_id}/reject", response_model=ShardOut)
def reject_shard(shard_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Reject a candidate — kept for provenance, never surfaces in search (AL-49)."""
    return _review_shard(shard_id, "rejected", "reject_shard", db, user)


@router.patch("/shards/{shard_id}", response_model=ShardOut)
def edit_shard(shard_id: str, body: ShardEdit, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    existing = db.get(MemoryShard, shard_id)
    if existing is None:
        raise HTTPException(404, "shard not found")
    if existing.project_id is not None:
        authz.require_writable(db, user.id, existing.project_id, "shard")
    elif not authz.writable_project_ids(db, user.id):
        raise HTTPException(403, "no write access to any project")
    shard = mem_svc.update_shard(db, shard_id, text_body=body.text)
    if shard is None:
        raise HTTPException(404, "shard not found")
    return shard


@router.post("/search", response_model=list[ShardHit])
def search(body: MemorySearchIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    hits = mem_svc.search_memory(db, body.query, top_k=body.top_k, project_id=body.project_id)
    return [ShardHit(shard=ShardOut.model_validate(s), score=round(score, 4)) for s, score in hits]


@router.post("/backfill")
def backfill(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return {"reembedded": mem_svc.backfill_embeddings(db)}


@router.get("/export")
def export(project_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if project_id is None:
        raise HTTPException(422, "project_id is required")
    authz.require_readable(db, user.id, project_id)
    return {"shards": mem_svc.export_shards(db, project_id=project_id)}


@router.post("/import")
def import_(body: ImportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    authz.require_writable(db, user.id, body.project_id)
    return {"imported": mem_svc.import_shards(db, body.shards, project_id=body.project_id)}
