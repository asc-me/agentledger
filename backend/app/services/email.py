"""Outbound email (AL-74b) — a deliberately small transport.

Org invites are the first (and, today, only) email AgentLedger sends. The policy
mirrors the rest of the codebase's "works offline, hardens for hosted" stance:

- SMTP configured (``SMTP_HOST`` set) — send for real over STARTTLS.
- SMTP unconfigured (self-host / tests) — log the message and append it to an
  in-process ``outbox`` instead. Nothing is lost, no infra is required, and tests
  assert on ``outbox`` the way Django's locmem backend works.

Sending never raises into the caller: a failed invite email must not 500 the
invite creation — the invite row (and its link) already exist, so delivery is
best-effort and logged, and the owner can always copy the link manually.
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger("agentledger.email")


@dataclass
class SentEmail:
    to: str
    subject: str
    text: str
    html: str | None = None


# In-process capture for the no-SMTP transport. Tests read this; a long-running
# self-host process would grow it unboundedly, so cap it.
outbox: list[SentEmail] = []
_OUTBOX_MAX = 200


def _record(msg: SentEmail) -> None:
    outbox.append(msg)
    if len(outbox) > _OUTBOX_MAX:
        del outbox[:-_OUTBOX_MAX]


def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Deliver an email. Returns True on send/queue, False on failure.

    With no ``SMTP_HOST`` this logs + records to :data:`outbox` and returns True;
    a real SMTP failure is caught, logged, and returns False (never raised)."""
    msg = SentEmail(to=to, subject=subject, text=text, html=html)

    if not settings.smtp_host:
        _record(msg)
        logger.info("[email:console] to=%s subject=%r\n%s", to, subject, text)
        return True

    email = EmailMessage()
    email["From"] = settings.smtp_from
    email["To"] = to
    email["Subject"] = subject
    email.set_content(text)
    if html:
        email.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_starttls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(email)
        _record(msg)
        return True
    except Exception:  # noqa: BLE001 — delivery is best-effort; never fail the caller
        logger.exception("failed to send email to %s", to)
        return False
