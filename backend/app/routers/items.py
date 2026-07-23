from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.schemas import ItemCreate, ItemOut, ItemUpdate, ReorderIn
from app.security import authz
from app.security.deps import get_current_user
from app.services import items as items_svc

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemOut])
def list_items(
    project_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authz.require_readable(db, user.id, project_id)
    return items_svc.list_items(db, project_id=project_id, status=status)


@router.post("", response_model=ItemOut, status_code=201)
def create_item(
    body: ItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    writable = authz.writable_project_ids(db, user.id)
    pid = body.project_id or (writable[0] if writable else None)
    authz.require_writable(db, user.id, pid)
    reporter = {"name": user.name, "handle": user.handle, "avatar": user.avatar}
    try:
        return items_svc.create_item(
            db,
            title=body.title,
            description=body.description,
            tags=body.tags,
            effort=body.effort,
            status=body.status,
            project_id=pid,
            touchpoints=body.touchpoints,
            prd_id=body.prd_id,
            prd_section=body.prd_section,
            reporter=reporter,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.patch("/reorder", response_model=list[ItemOut])
def reorder(
    body: ReorderIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Every project the reordered items span must be writable by the caller.
    rows = [items_svc.get_item(db, i) for i in body.ordered_ids]
    for pid in {r.project_id for r in rows if r is not None}:
        authz.require_writable(db, user.id, pid, "item")
    return items_svc.reorder_items(db, body.ordered_ids)


@router.get("/{item_id}", response_model=ItemOut)
def get_item(item_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    item = items_svc.get_item(db, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return item


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(
    item_id: str,
    body: ItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = items_svc.get_item(db, item_id)
    if existing is None:
        raise HTTPException(404, "item not found")
    authz.require_writable(db, user.id, existing.project_id, "item")
    try:
        item = items_svc.update_item(db, item_id, **body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if item is None:
        raise HTTPException(404, "item not found")
    return item
