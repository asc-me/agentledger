"""Request network metadata — shared client-IP resolution for rate limiting."""
from __future__ import annotations

from starlette.requests import Request

from app.config import settings


def client_ip(request: Request) -> str:
    """The caller's IP for a rate-limit bucket. Behind a proxy/LB the socket peer is
    the proxy, so every client would share one bucket; honor the first
    X-Forwarded-For hop ONLY when the operator asserts a trusted proxy sits in front
    (otherwise the header is client-spoofable)."""
    if settings.trusted_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
