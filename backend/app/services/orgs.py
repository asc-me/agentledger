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


def create_platform_invite(db: Session, email: str, plan: str | None, inviter: User) -> OrgInvite:
    """Operator-issued invite authorizing a BRAND-NEW account to sign up and found its
    own org (AL-91). Commits.

    Refused when an account already exists for the email: platform invites are for
    net-new customers, and an existing user wanting another org goes through the
    additional-org request flow instead. Optionally carries a ``plan`` to stamp on the
    org they found. Re-inviting a still-pending email refreshes rather than duplicates."""
    email = email.strip().lower()
    if not email:
        raise HTTPException(422, "invitee email is required")
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(
            409,
            "an account already exists for that email — platform invites are for new "
            "customers; an existing user needs an additional-org request instead",
        )

    invite = db.scalar(
        select(OrgInvite).where(
            OrgInvite.kind == "platform",
            OrgInvite.email == email,
            OrgInvite.status == "pending",
        )
    )
    if invite is None:
        invite = OrgInvite(
            id="inv_" + uuid.uuid4().hex[:12],
            kind="platform",
            org_id=None,
            email=email,
            invited_by=inviter.id,
        )
        db.add(invite)
    invite.plan = plan
    invite.token = secrets.token_urlsafe(32)
    invite.expires_at = utcnow() + timedelta(days=settings.invite_expiry_days)
    db.commit()
    db.refresh(invite)

    _send_platform_invite_email(invite, inviter)
    return invite


def _send_platform_invite_email(invite: OrgInvite, inviter: User) -> None:
    link = f"{settings.app_base_url.rstrip('/')}/invite/{invite.token}"
    subject = "You're invited to AgentLedger"
    who = inviter.name or inviter.handle or "The AgentLedger team"
    text = (
        f"{who} invited you to AgentLedger.\n\n"
        f"Create your account and set up your organization:\n{link}\n\n"
        f"This link expires in {settings.invite_expiry_days} days. If you didn't expect "
        f"this, you can ignore this email."
    )
    email_svc.send_email(invite.email, subject, text)


def pending_platform_invites(db: Session) -> list[OrgInvite]:
    return list(
        db.scalars(
            select(OrgInvite)
            .where(OrgInvite.kind == "platform", OrgInvite.status == "pending")
            .order_by(OrgInvite.created_at.desc())
        )
    )


def platform_plan_for(db: Session, user: User) -> str | None:
    """The plan preset from the platform invite this user signed up with, if any.

    Only meaningful while founding their FIRST org — the caller checks that — so no
    separate consumed flag is needed and the invite keeps its provenance."""
    invite = db.scalar(
        select(OrgInvite).where(
            OrgInvite.kind == "platform",
            OrgInvite.accepted_user_id == user.id,
            OrgInvite.status == "accepted",
        )
    )
    return invite.plan if invite else None


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
    if invite.kind == "platform":
        # A platform invite is redeemed by REGISTERING with it (which founds a new org),
        # not by joining an existing one. An already-signed-in user can't consume it.
        raise HTTPException(
            400,
            "this is a platform invitation — redeem it by creating a new account; an "
            "existing account needs an additional-org request instead",
        )
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


def accept_platform_invite(db: Session, token: str, user: User) -> OrgInvite:
    """Mark a platform invite redeemed by the account that just registered (AL-91).

    There is no org to join — the invite authorized the *account*; the user then founds
    their own org, and :func:`platform_plan_for` applies any plan preset at that point."""
    invite = _validate_pending(invite_by_token(db, token))
    if invite.kind != "platform":
        raise HTTPException(400, "not a platform invitation")
    if invite.email.lower() != (user.email or "").lower():
        raise HTTPException(403, "this invitation was sent to a different email address")
    invite.status = "accepted"
    invite.accepted_at = utcnow()
    invite.accepted_user_id = user.id
    db.commit()
    return invite


def revoke_invite(db: Session, invite: OrgInvite) -> None:
    """Cancel a pending invite so its link stops working. Commits."""
    invite.status = "revoked"
    db.commit()


def pending_invites(db: Session, org_id: str) -> list[OrgInvite]:
    """Pending invites for one org — org-kind only, so the operator's platform
    invites never surface inside a tenant's member list."""
    return list(
        db.scalars(
            select(OrgInvite)
            .where(
                OrgInvite.kind == "org",
                OrgInvite.org_id == org_id,
                OrgInvite.status == "pending",
            )
            .order_by(OrgInvite.created_at.desc())
        )
    )
