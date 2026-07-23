from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, Project, User
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.security import authz
from app.security.apikey import generate_api_key
from app.security.deps import get_current_user
from app.services import events as events_svc

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyOut])
def list_keys(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list(db.scalars(select(ApiKey).where(ApiKey.user_id == user.id)).all())


@router.post("", response_model=ApiKeyCreated, status_code=201)
def create_key(body: ApiKeyCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.project_id is not None:
        if db.get(Project, body.project_id) is None:
            raise HTTPException(422, f"unknown project: {body.project_id!r}")
        # A key inherits its power from its owner's memberships; minting one for a
        # project the owner can't read would only produce a dead key.
        authz.require_readable(db, user.id, body.project_id)
    row, plaintext = generate_api_key(
        db, user.id, body.name, body.scopes, body.project_id, body.expires_in_days
    )
    events_svc.record_user(db, user, action="create_api_key", target_type="api_key",
                           target_id=row.id, project_id=row.project_id,
                           meta={"name": row.name, "scopes": row.scopes})
    out = ApiKeyCreated.model_validate({**ApiKeyOut.model_validate(row).model_dump(), "plaintext": plaintext})
    return out


@router.delete("/{key_id}", status_code=204)
def revoke_key(key_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(ApiKey, key_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "key not found")
    project_id, name = row.project_id, row.name
    db.delete(row)
    db.commit()
    events_svc.record_user(db, user, action="revoke_api_key", target_type="api_key",
                           target_id=key_id, project_id=project_id, meta={"name": name})
