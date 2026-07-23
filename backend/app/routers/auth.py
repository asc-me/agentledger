import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Membership, Project, User
from app.schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from app.security.deps import get_current_user
from app.security.jwt import create_access_token, create_refresh_token, decode_token
from app.security.net import client_ip
from app.security.passwords import hash_password, verify_password
from app.services import spam

router = APIRouter(prefix="/auth", tags=["auth"])


def _guard_login_rate(request: Request, email: str) -> None:
    """Blunt credential stuffing / brute force (AL-72): cap attempts per-email and,
    more loosely, per source IP. Counts every attempt, so a wrong-password flood
    trips the limit and returns 429 instead of letting guessing run unbounded."""
    per_email = settings.login_rate_per_min
    per_ip = per_email * 3  # an IP may legitimately host several accounts
    ip = client_ip(request)
    if not spam.check_rate(f"login:email:{email.lower()}", per_email) or not spam.check_rate(
        f"login:ip:{ip}", per_ip
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many login attempts; try again shortly")


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    _guard_login_rate(request, body.email)
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return TokenOut(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not settings.open_registration:
        # Invite-only / hosted private beta: no self-serve signup (AL-72). The invite
        # flow lands with the org onboarding work (AL-74).
        raise HTTPException(status.HTTP_403_FORBIDDEN, "registration is closed")
    exists = db.scalar(
        select(User).where((User.email == body.email) | (User.handle == body.handle))
    )
    if exists is not None:
        # Generic message — don't disclose which of email/handle is taken (AL-72).
        raise HTTPException(status.HTTP_409_CONFLICT, "could not create account with those details")
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
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    # A refresh token from before the last logout/password-change is dead (AL-59).
    if payload.get("tv", 0) != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token revoked")
    return TokenOut(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )


@router.post("/logout", status_code=204)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Server-side logout (AL-59): bump the user's token_version so every access AND
    refresh token issued so far — on any device — stops validating immediately."""
    user.token_version += 1
    db.commit()


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
