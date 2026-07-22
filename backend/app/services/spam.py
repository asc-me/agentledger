"""Spam protection for the public feedback endpoints.

Three layers, cheapest first:
1. Honeypot — a hidden field real users never fill.
2. Per-(project, IP) sliding-window rate limit, with a per-project configurable cap.
3. Optional Cloudflare Turnstile — verified only when a project configures a secret
   (so the app stays fully offline by default).
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque

_WINDOW = 60.0  # seconds
_hits: dict[str, deque] = defaultdict(deque)


def check_rate(key: str, limit: int) -> bool:
    """Return True if this call is under the limit for `key` in the last minute."""
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > _WINDOW:
        q.popleft()
    if len(q) >= max(1, limit):
        return False
    q.append(now)
    return True


def verify_turnstile(secret: str, token: str, remoteip: str | None = None) -> bool:
    """Verify a Turnstile token. No secret configured → not required (returns True)."""
    if not secret:
        return True
    if not token:
        return False
    data = {"secret": secret, "response": token}
    if remoteip:
        data["remoteip"] = remoteip
    try:
        req = urllib.request.Request(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=urllib.parse.urlencode(data).encode(),
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 — fixed trusted host
            body = json.loads(resp.read())
        return bool(body.get("success"))
    except Exception:
        return False
