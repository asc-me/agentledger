"""Observability floor (Phase 5, AL-56): structured logging + request correlation.

- Every request gets an id (an inbound ``X-Request-ID`` is honored, else one is
  generated), stashed in a contextvar, echoed on the response, and stamped on every
  log line emitted while handling it — so logs across the API and MCP dispatcher for
  one request line up.
- Logging is human-readable text by default; ``LOG_JSON=true`` switches to one JSON
  object per line for ingestion by a log platform. ``LOG_LEVEL`` sets the threshold.

The middleware is pure ASGI (not BaseHTTPMiddleware) so it never buffers the
response body — the SSE streaming endpoints keep streaming.
"""
from __future__ import annotations

import contextvars
import json
import logging
import uuid

from app.config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    """Install the app's root log handler. Idempotent — safe to call on each boot."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(_JsonFormatter() if settings.log_json else logging.Formatter(_TEXT_FORMAT))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # uvicorn's access log duplicates what we already see; quiet it to WARNING.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class RequestIdMiddleware:
    """ASGI middleware: assign/propagate a request id and echo it on the response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id")
        rid = incoming.decode() if incoming else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)
