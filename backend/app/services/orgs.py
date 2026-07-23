"""Organization + invite domain logic (hosted-only, AL-74b).

One owner for the org lifecycle: create an org (creator becomes owner), invite a
teammate by email, and accept an emailed invite (join the org). The org router is
the only caller; authority checks (who may invite) live in ``security.authz`` and
are applied at the router boundary. This module owns the *rules* of an invite —
single-use, email-bound, time-bounded — and raises :class:`HTTPException` for the
ones a caller can trip, so the router stays thin.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import OrgInvite, OrgMembership, Organization, User, utcnow
from app.services import email as email_svc
from app.services import quotas


def create_org(db: Session, user: User, name: str) -> Organization:
    """Create an org and seat its creator as owner. Commits."""
    name = name.strip()
    if not name:
        raise HTTPException(422, "organization name is required")
    org = Organization(id="org_" + uuid.uuid4().hex[:10], name=name)
    db.add(org)
    db.flush()
    db.add(OrgMembership(org_id=org.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(org)
    return org


def create_invite(db: Session, org: Organization, email: str, role: str, inviter: User) -> OrgInvite:
    """Create a pending invite and email the accept link. Commits.

    An owner can grant admin or member; ``owner`` is never invitable (ownership is a
    creation/transfer concern, not an invite one). A still-pending invite to the same
    email is reused rather than duplicated, so re-inviting just re-sends the link."""
    email = email.strip().lower()
    if not email:
        raise HTTPException(422, "invitee email is required")
    role = role if role in ("admin", "member") else "member"

    invite = db.scalar(
        select(OrgInvite).where(
            OrgInvite.org_id == org.id,
            OrgInvite.email == email,
            OrgInvite.status == "pending",
        )
    )
    if invite is None:
        # A fresh invite reserves a seat; re-inviting the same pending email doesn't,
        # so only gate the new-invite path against the plan's seat cap.
        quotas.enforce_seat_quota(db, org.id)
        invite = OrgInvite(
            id="inv_" + uuid.uuid4().hex[:12],
            org_id=org.id,
            email=email,
            invited_by=inviter.id,
        )
        db.add(invite)
    invite.role = role
    invite.token = secrets.token_urlsafe(32)
    invite.expires_at = utcnow() + timedelta(days=settings.invite_expiry_days)
    db.commit()
    db.refresh(invite)

    _send_invite_email(invite, org, inviter)
    return invite


def _send_invite_email(invite: OrgInvite, org: Organization, inviter: User) -> None:
    link = f"{settings.app_base_url.rstrip('/')}/invite/{invite.token}"
    subject = f"You're invited to join {org.name} on AgentLedger"
    who = inviter.name or inviter.handle or "A teammate"
    text = (
        f"{who} invited you to join the “{org.name}” organization on AgentLedger "
        f"as {invite.role}.\n\n"
        f"Accept your invitation:\n{link}\n\n"
        f"This link expires in {settings.invite_expiry_days} days. If you didn't expect "
        f"this, you can ignore this email."
    )
    email_svc.send_email(invite.email, subject, text)


def invite_by_token(db: Session, token: str) -> OrgInvite | None:
    return db.scalar(select(OrgInvite).where(OrgInvite.token == token))


def _validate_pending(invite: OrgInvite | None) -> OrgInvite:
    """Shared gate for reading/accepting an invite: it must exist, be pending, and
    not be expired. 404 (not 403) so a bad/used token can't be told apart from a
    non-existent one."""
    if invite is None or invite.status != "pending":
        raise HTTPException(404, "invitation not found or already used")
    if invite.expires_at is not None:
        # SQLite hands datetimes back tz-naive; coerce to UTC before comparing (as the
        # api-key expiry check does) so aware/naive never collide.
        exp = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
        if exp < utcnow():
            raise HTTPException(410, "this invitation has expired")
    return invite


def accept_invite(db: Session, token: str, user: User) -> Organization:
    """Join the invite's org as the accepting user. Commits.

    The invite is email-bound: the logged-in user's email must match the address it
    was sent to, so a forwarded link can't be redeemed by a different account. Joining
    is idempotent — a user who is already a member just marks the invite accepted."""
    invite = _validate_pending(invite_by_token(db, token))
    if invite.email.lower() != (user.email or "").lower():
        raise HTTPException(403, "this invitation was sent to a different email address")

    org = db.get(Organization, invite.org_id)
    if org is None:  # org deleted out from under the invite
        raise HTTPException(404, "invitation not found or already used")

    existing = db.scalar(
        select(OrgMembership).where(
            OrgMembership.org_id == invite.org_id, OrgMembership.user_id == user.id
        )
    )
    if existing is None:
        db.add(OrgMembership(org_id=invite.org_id, user_id=user.id, role=invite.role))
    invite.status = "accepted"
    invite.accepted_at = utcnow()
    invite.accepted_user_id = user.id
    db.commit()
    return org


def revoke_invite(db: Session, invite: OrgInvite) -> None:
    """Cancel a pending invite so its link stops working. Commits."""
    invite.status = "revoked"
    db.commit()


def pending_invites(db: Session, org_id: str) -> list[OrgInvite]:
    return list(
        db.scalars(
            select(OrgInvite)
            .where(OrgInvite.org_id == org_id, OrgInvite.status == "pending")
            .order_by(OrgInvite.created_at.desc())
        )
    )
