"""Domain error taxonomy — one owner for "what went wrong" across the app.

Raised by services and the MCP dispatcher; the dispatcher maps each to a stable
machine-readable ``code`` in the JSON-RPC tool error so an agent can branch
without parsing prose (AL-47 / review finding F6). REST routers may also catch
these, though most still use HTTPException directly.

Codes: ``not_found`` · ``validation`` · ``conflict`` (authorization uses a
separate ``unauthorized`` code, owned by ``security/authz.Forbidden``).
"""
from __future__ import annotations


class AppError(Exception):
    """Base for expected, agent-correctable failures. ``hint`` names the fix."""

    code = "internal"

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class NotFound(AppError):
    """A referenced resource does not exist (or is not visible)."""

    code = "not_found"


class Validation(AppError):
    """The arguments are malformed: missing required field, bad enum, wrong type."""

    code = "validation"


class Conflict(AppError):
    """The request collides with current state: lost lease, reused idempotency key."""

    code = "conflict"
