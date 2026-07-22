"""Report an issue with AgentLedger — the in-app (authenticated) side of the upstream
feedback channel. Forwards a user-initiated report to the maintainer's intake."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.models import User
from app.schemas import UpstreamReportIn
from app.security.deps import get_current_user
from app.services import upstream as up_svc

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/upstream")
def upstream_config(_: User = Depends(get_current_user)):
    """Whether upstream reporting is on and where reports go — the UI uses this to show/hide
    the action and to tell the user (transparently) where their report is sent."""
    return {"enabled": up_svc.report_enabled(), "target": up_svc.target_host()}


@router.post("/upstream")
def upstream_report(body: UpstreamReportIn, _: User = Depends(get_current_user)):
    try:
        result = up_svc.submit_upstream(
            type_=body.type, title=body.title, detail=body.detail, source="in-app"
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"upstream unreachable: {e}")
    req = result.get("request", {})
    return {"ok": True, "request_id": req.get("id"), "duplicates": result.get("duplicates", [])}
