from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

import jwt

from app.db import get_db
from app.models import ApiKey, User
from app.security.apikey import verify_api_key
from app.security.jwt import decode_token


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the logged-in user from a `Bearer <access-jwt>` header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


def get_agent_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Resolve an agent API key from `X-API-Key` or `Authorization: Bearer al_sk_...`."""
    raw = x_api_key
    if not raw and authorization and authorization.lower().startswith("bearer "):
        candidate = authorization.split(" ", 1)[1]
        if candidate.startswith("al_sk_"):
            raw = candidate
    key = verify_api_key(db, raw or "")
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
    return key
