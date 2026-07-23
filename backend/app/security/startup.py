"""Startup security checks (AL-44 / review finding F2).

The app must never silently boot internet-exposed with the well-known default
JWT secret — anyone knowing it can mint tokens for any user. We can't reliably
detect "is this production?", so the policy is:

- SQLite (tests / zero-infra local) — skip; a throwaway DB isn't a target.
- Otherwise — always emit a loud warning on a weak/default secret, and REFUSE to
  start when the operator has opted into enforcement (``REQUIRE_STRONG_SECRET``).

This keeps `docker compose up` working out of the box while giving a one-flag
hardening switch for a real deploy.
"""
from __future__ import annotations

from app.config import settings

_BANNER = "=" * 72


def check_security() -> None:
    if settings.is_sqlite:
        return

    # Hosted (multi-tenant) mode must encrypt BYOK provider keys at rest — refuse to
    # boot a shared instance that would store tenants' keys in plaintext (AL-73).
    if settings.hosted_mode and not settings.secret_encryption_key:
        raise RuntimeError(
            "refusing to start: HOSTED_MODE is on but SECRET_ENCRYPTION_KEY is unset — "
            "tenant provider keys would be stored in plaintext. Set a strong "
            "SECRET_ENCRYPTION_KEY."
        )

    if not settings.jwt_secret_is_weak:
        return

    message = (
        "JWT_SECRET is weak or the built-in default. Anyone who knows it can forge "
        "auth tokens for any user. Set JWT_SECRET to a long random string (>=32 bytes) "
        "before exposing this instance."
    )
    if settings.require_strong_secret:
        raise RuntimeError(
            f"refusing to start: {message} "
            "(REQUIRE_STRONG_SECRET is on)"
        )
    print(f"\n{_BANNER}\n  SECURITY WARNING: {message}\n{_BANNER}\n", flush=True)
