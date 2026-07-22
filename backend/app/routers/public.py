"""Public, unauthenticated feedback intake (Phase 2, AL-19 + AL-21).

Powers the embeddable feedback widget. No JWT — protected instead by a simple
per-IP sliding-window rate limit and a project-scoped enable flag.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request as FastAPIRequest
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.schemas import DuplicateHit, PublicRequestIn, PublicRequestOut, RequestOut
from app.services import duplicates as dup_svc
from app.services import items as items_svc
from app.services import requests as req_svc
from app.services import roadmap as roadmap_svc
from app.services.projects import default_project_id, resolve_project_id

router = APIRouter(prefix="/public", tags=["public"])

_RATE_WINDOW = 60.0  # seconds
_RATE_MAX = 20  # requests per window per IP
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: FastAPIRequest) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_MAX:
        raise HTTPException(429, "too many submissions, slow down")
    q.append(now)


def _ensure_enabled() -> None:
    if not settings.public_submit_enabled:
        raise HTTPException(403, "public submissions are disabled")


@router.get("/roadmap")
def public_roadmap(project_id: str | None = None, db: Session = Depends(get_db)):
    """Read-only public roadmap for the shareable link."""
    return roadmap_svc.list_roadmap(db, project_id=resolve_project_id(db, project_id))


@router.post("/github/webhook")
async def github_webhook(
    request: FastAPIRequest, _rl: None = Depends(rate_limit), db: Session = Depends(get_db)
):
    """Inbound GitHub issues webhook → new tracker item.

    (Real deployments verify the X-Hub-Signature-256 HMAC; omitted for the local slice.)
    """
    payload = await request.json()
    if payload.get("action") not in ("opened", "reopened"):
        return {"ignored": True, "action": payload.get("action")}
    issue = payload.get("issue", {}) or {}
    item = items_svc.create_item(
        db,
        title=issue.get("title", "Untitled GitHub issue"),
        description=issue.get("body", "") or "",
        tags=["github"],
        project_id=default_project_id(db),
        reporter={"name": "GitHub", "handle": "github", "avatar": "#8b949e"},
    )
    return {"created_item": item.id}


@router.get("/duplicates", response_model=list[DuplicateHit])
def check_duplicates(
    q: str,
    project_id: str | None = None,
    _rl: None = Depends(rate_limit),
    db: Session = Depends(get_db),
):
    """Live duplicate check for the widget — before the user submits."""
    _ensure_enabled()
    return dup_svc.find_duplicates(db, q, project_id=resolve_project_id(db, project_id))


@router.post("/requests", response_model=PublicRequestOut, status_code=201)
def submit_request(
    body: PublicRequestIn,
    _rl: None = Depends(rate_limit),
    db: Session = Depends(get_db),
):
    _ensure_enabled()
    text = f"{body.title} {body.detail}".strip()
    project_id = resolve_project_id(db, body.project_id)
    try:
        req = req_svc.create_request(
            db, type_=body.type, title=body.title,
            by=body.email or "public", project_id=project_id,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    dups = dup_svc.find_duplicates(db, text, project_id=project_id, exclude_request_id=req.id)
    return PublicRequestOut(
        request=RequestOut.model_validate(req),
        duplicates=[DuplicateHit(**d) for d in dups],
    )
