"""Per-tool MCP call metering (Phase 4 — powers the MCP Tools page)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import McpToolStat


def increment(db: Session, tool: str) -> None:
    stat = db.get(McpToolStat, tool)
    if stat is None:
        stat = McpToolStat(tool=tool, calls=0)
        db.add(stat)
    stat.calls += 1
    db.commit()


def counts(db: Session) -> dict[str, int]:
    return {s.tool: s.calls for s in db.scalars(select(McpToolStat)).all()}


def total(db: Session) -> int:
    return sum(s.calls for s in db.scalars(select(McpToolStat)).all())
