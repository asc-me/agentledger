"""First-run bootstrap guidance (AL-133).

`setup_project` returns an ordered, RESUMABLE checklist that walks a fresh project from empty to
useful — confirm the right project, build the code graph, load memories, propose work items
(v1 steps 1–4). It's a GUIDE, not an executor: each step reports done/pending from the project's
current state and tells the agent how to do it with the existing tools, so re-running just
reflects progress (idempotent). The heavy code-graph pass is local-first (AL-134) — no hosted
call quota. `get_context` flags an empty project and points here.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CodeNode, Item, MemoryShard

# Sources are EXTENSIBLE — editor conventions (.cursor/rules, Grok Build GROK.md, Codex
# AGENTS.md) plug in later (AL-133 D2).
_MEMORY_SOURCES = ["AGENTS.md", "CLAUDE.md", "docs/"]
_ITEM_SOURCES = ["TODO/FIXME comments", "PLAN.md", "ROADMAP.md"]


def counts(db: Session, project_id: str) -> tuple[int, int, int]:
    """(code nodes, items, memory shards) for a project — the bootstrap progress signal."""
    nodes = db.scalar(select(func.count()).select_from(CodeNode).where(CodeNode.project_id == project_id)) or 0
    items = db.scalar(select(func.count()).select_from(Item).where(Item.project_id == project_id)) or 0
    shards = db.scalar(select(func.count()).select_from(MemoryShard).where(MemoryShard.project_id == project_id)) or 0
    return nodes, items, shards


def is_empty(db: Session, project_id: str) -> bool:
    """No graph, no items, no memory — the first-run signal get_context surfaces."""
    return counts(db, project_id) == (0, 0, 0)


def checklist(db: Session, project_id: str) -> dict:
    nodes, items, shards = counts(db, project_id)
    steps = [
        {"step": 1, "name": "Confirm the project", "status": "action_required",
         "detail": f"You're set to write into '{project_id}'.",
         "how": "A HUMAN confirms this is the right workspace before bootstrapping — writing into "
                "the wrong project pollutes another (in hosted mode, another tenant). Don't guess."},
        {"step": 2, "name": "Build the code graph", "status": "done" if nodes else "pending",
         "detail": f"{nodes} code node(s) described.",
         "how": "describe_code across the repo (link_code to bridge items↔paths). LOCAL-FIRST: run "
                "on the local instance so the pass never hits the hosted call quota (AL-134); "
                "cloud-only, request a dry-run size/cost estimate + a budget first."},
        {"step": 3, "name": "Load memories", "status": "done" if shards else "pending",
         "detail": f"{shards} memory shard(s).",
         "how": "Read the convention files and add_memory each durable fact as a CANDIDATE "
                "(human-reviewed, never auto-published).",
         "sources": _MEMORY_SOURCES},
        {"step": 4, "name": "Propose work items", "status": "done" if items else "pending",
         "detail": f"{items} item(s).",
         "how": "Scan the sources and create_item to PROPOSE work (deduped against existing items, "
                "capped) — never bulk-create a flood.",
         "sources": _ITEM_SOURCES},
    ]
    # Step 1 is always a human confirmation; completeness is about steps 2–4 having content.
    complete = all(s["status"] == "done" for s in steps[1:])
    return {
        "project_id": project_id,
        "empty": (nodes, items, shards) == (0, 0, 0),
        "complete": complete,
        "steps": steps,
        "note": "Resumable + idempotent — re-run any time; done steps reflect current state.",
    }
