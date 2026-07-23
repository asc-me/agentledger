from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Request, User
from app.schemas import RequestCreate, RequestLinkIn, RequestOut, RequestVoteIn
from app.security import authz
from app.security.deps import get_current_user
from app.services import requests as req_svc

router = APIRouter(prefix="/requests", tags=["requests"])


@router.get("", response_model=list[RequestOut])
def list_requests(
    project_id: str | None = None,
    type: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authz.require_readable(db, user.id, project_id)
    return req_svc.list_requests(db, project_id=project_id, type_=type)


@router.post("", response_model=RequestOut, status_code=201)
def create_request(body: RequestCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    authz.require_writable(db, user.id, body.project_id)
    try:
        return req_svc.create_request(
            db, type_=body.type, title=body.title, by=body.by, project_id=body.project_id
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/{request_id}/vote", response_model=RequestOut)
def vote(request_id: str, body: RequestVoteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    existing = db.get(Request, request_id)
    if existing is None:
        raise HTTPException(404, "request not found")
    authz.require_writable(db, user.id, existing.project_id, "request")
    req = req_svc.vote_request(db, request_id, body.delta)
    if req is None:
        raise HTTPException(404, "request not found")
    return req


@router.post("/{request_id}/link", response_model=RequestOut)
def link(request_id: str, body: RequestLinkIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    existing = db.get(Request, request_id)
    if existing is None:
        raise HTTPException(404, "request not found")
    authz.require_writable(db, user.id, existing.project_id, "request")
    try:
        req = req_svc.link_request(db, request_id, body.item_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if req is None:
        raise HTTPException(404, "request not found")
    return req
