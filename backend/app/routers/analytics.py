"""Read-only aggregation endpoints for the Dashboard, Roadmap, Links, and MCP views."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.mcp_server import TOOLS
from app.models import User
from app.security.deps import get_current_user
from app.services import dashboard as dash_svc
from app.services import links as links_svc
from app.services import mcp_stats
from app.services import roadmap as roadmap_svc

router = APIRouter(tags=["analytics"])


@router.get("/dashboard")
def dashboard(project_id: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return dash_svc.build(db, project_id=project_id)


@router.get("/roadmap")
def roadmap(project_id: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return roadmap_svc.list_roadmap(db, project_id=project_id)


@router.get("/links")
def links(project_id: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = links_svc.list_links(db, project_id=project_id)
    return [
        {"id": l.id, "a": l.a, "b": l.b, "type": l.type, "confidence": l.confidence, "reason": l.reason}
        for l in rows
    ]


@router.get("/mcp/tools")
def mcp_tools(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    counts = mcp_stats.counts(db)
    return {
        "live": len(TOOLS),
        "tools": [
            {
                "name": t["name"],
                "description": t["description"],
                "params": list(t["inputSchema"].get("properties", {}).keys()),
                "calls": counts.get(t["name"], 0),
                "status": "live",
            }
            for t in TOOLS
        ],
    }
