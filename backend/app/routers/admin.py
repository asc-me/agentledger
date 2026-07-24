"""Platform (operator) plane — hosted-only, platform-admin-only (AL-91).

This is the one deliberate cross-tenant surface in the product. Two hard rules keep it
from becoming the isolation hole that Phase 6 (AL-76) exists to prevent:

1. **Gated twice** — HOSTED_MODE must be on AND the caller must be a platform operator
   (``PLATFORM_ADMIN_EMAILS``). Failure is a 404, not a 403, so the surface's very
   existence stays hidden from tenants.
2. **Metadata only** — nothing here returns tenant *content* (items, memory shards,
   PRDs, requests, code graph). Operators see orgs, plans, usage, and invites; never
   what a customer wrote.

Every mutation is recorded to the event ledger, attributed to the acting operator.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import OrgInvite, User
from app.schemas import InviteOut, PlatformInviteCreate
from app.security.deps import get_current_user
from app.services import events as events_svc
from app.services import orgs as orgs_svc
from app.services import quotas


def require_platform_admin(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> User:
    """Hosted + operator-allowlist gate. 404 (not 403) hides the plane from tenants."""
    if not settings.hosted_mode or not quotas.is_platform_admin(user):
        raise HTTPException(404, "Not Found")
    return user


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)])


def _invite_out(invite: OrgInvite) -> InviteOut:
    out = InviteOut.model_validate(invite)
    out.accept_url = f"{settings.app_base_url.rstrip('/')}/invite/{invite.token}"
    return out


@router.get("/invites", response_model=list[InviteOut])
def list_platform_invites(db: Session = Depends(get_db)):
    """Pending platform invites — the beta's outstanding onboarding links."""
    return [_invite_out(i) for i in orgs_svc.pending_platform_invites(db)]


@router.post("/invites", response_model=InviteOut, status_code=201)
def create_platform_invite(
    body: PlatformInviteCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_platform_admin),
):
    """Invite a NEW customer: they sign up and found their own org. Refused if an
    account already exists for the email (that's an additional-org request instead)."""
    if body.plan is not None and body.plan not in quotas.PLANS:
        raise HTTPException(422, f"unknown plan {body.plan!r}; expected one of {', '.join(quotas.PLANS)}")
    invite = orgs_svc.create_platform_invite(db, body.email, body.plan, admin)
    events_svc.record_user(db, admin, action="create_platform_invite", target_type="org_invite",
                           target_id=invite.id, meta={"email": invite.email, "plan": invite.plan})
    return _invite_out(invite)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_platform_invite(
    invite_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_platform_admin),
):
    invite = db.get(OrgInvite, invite_id)
    if invite is None or invite.kind != "platform" or invite.status != "pending":
        raise HTTPException(404, "invitation not found")
    orgs_svc.revoke_invite(db, invite)
    events_svc.record_user(db, admin, action="revoke_platform_invite", target_type="org_invite",
                           target_id=invite.id, meta={"email": invite.email})
