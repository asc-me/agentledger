import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Membership, Project, User
from app.schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from app.security.deps import get_current_user
from app.security.jwt import create_access_token, create_refresh_token, decode_token
from app.security.passwords import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return TokenOut(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    exists = db.scalar(
        select(User).where((User.email == body.email) | (User.handle == body.handle))
    )
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email or handle already in use")
    initials = "".join(p[0] for p in body.name.split()[:2]).upper() or body.name[:2].upper()
    user = User(
        id="u_" + uuid.uuid4().hex[:8],
        name=body.name,
        email=body.email,
        handle=body.handle.lstrip("@"),
        initials=initials,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    return TokenOut(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    uid = payload.get("sub")
    if db.get(User, uid) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return TokenOut(access_token=create_access_token(uid), refresh_token=create_refresh_token(uid))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/me/memberships")
def my_memberships(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    out = []
    for m in rows:
        project = db.get(Project, m.project_id)
        out.append({
            "project_id": m.project_id,
            "project_name": project.name if project else m.project_id,
            "accent": project.accent if project else "#c6f24e",
            "role": m.role,
            "access": m.access,
        })
    return out
