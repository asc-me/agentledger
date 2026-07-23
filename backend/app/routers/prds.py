from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.schemas import (
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
from app.services import prds as prd_svc

router = APIRouter(prefix="/prds", tags=["prds"])


def _require_writable_prd(db: Session, user: User, prd_id: str) -> None:
    """Load-and-guard for PRD mutations: 404 unknown, 404/403 per membership."""
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    authz.require_writable(db, user.id, prd.project_id, "prd")


@router.get("", response_model=list[PrdSummary])
def list_prds(project_id: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return prd_svc.list_prds(db, project_id=project_id)


@router.post("", response_model=PrdOut, status_code=201)
def create_prd(body: PrdCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    authz.require_writable(db, user.id, body.project_id)
    return prd_svc.create_prd(
        db, title=body.title, template=body.template, project_id=body.project_id, body=body.body,
    )


@router.get("/{prd_id}/coverage")
def prd_coverage(prd_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    return prd_svc.coverage(db, prd)


@router.post("/{prd_id}/decompose")
def decompose_prd(prd_id: str, create: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    if create:  # proposing tasks is a read; creating them is a write
        authz.require_writable(db, user.id, prd.project_id, "prd")
    return prd_svc.decompose(db, prd, create=create)


@router.get("/{prd_id}", response_model=PrdOut)
def get_prd(prd_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
    return prd


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
def list_versions(prd_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    prd = prd_svc.get_prd(db, prd_id)
    if prd is None:
        raise HTTPException(404, "prd not found")
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
