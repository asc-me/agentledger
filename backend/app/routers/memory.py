from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.schemas import MemorySearchIn, ShardCreate, ShardHit, ShardOut
from app.security.deps import get_current_user
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
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return mem_svc.list_shards(db, project_id=project_id)


@router.post("/shards", response_model=ShardOut, status_code=201)
def add_shard(body: ShardCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return mem_svc.add_memory(
        db,
        text_body=body.text,
        scope=body.scope,
        item_id=body.item_id,
        project_id=body.project_id,
    )


@router.patch("/shards/{shard_id}", response_model=ShardOut)
def edit_shard(shard_id: str, body: ShardEdit, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
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
def export(project_id: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return {"shards": mem_svc.export_shards(db, project_id=project_id)}


@router.post("/import")
def import_(body: ImportIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return {"imported": mem_svc.import_shards(db, body.shards, project_id=body.project_id)}
