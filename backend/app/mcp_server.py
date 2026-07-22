"""MCP endpoint (JSON-RPC 2.0 over HTTP).

Exposes the 5 live AgentLedger tools to agents, authenticated by a scoped API key.
Every tool calls the shared service layer, so an agent's writes are identical to
what the web app produces — one code path.

Handled methods: `initialize`, `tools/list`, `tools/call`, and the
`notifications/initialized` notification. Single JSON responses (no SSE) keep it
`curl`-friendly while remaining MCP Streamable-HTTP compatible for simple calls.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, Item, Link, MemoryShard, Project
from app.security.deps import get_agent_key
from app.services import clustering as cluster_svc
from app.services import idempotency as idem_svc
from app.services import insights as insights_svc
from app.services import items as items_svc
from app.services import links as links_svc
from app.services import mcp_stats
from app.services import memory as mem_svc
from app.services.projects import resolve_project_id

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSION = "2025-06-18"

logger = logging.getLogger("agentledger.mcp")

_STATUS_ENUM = items_svc.STATUSES
_EFFORT_DESC = "Relative effort estimate, integer (higher = more work). No fixed unit."

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_context",
        "description": (
            "Orient yourself: returns the project this API key writes to, your scopes, and how "
            "many projects and tools exist. Call this first when you start."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_projects",
        "description": "List all projects (id, name, accent, description). Use an id as the `project_id` override.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_item",
        "description": "Create a tracker item. Returns the created item incl. its id and project_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string", "description": "Markdown body."},
                "tags": {"type": "array", "items": {"type": "string"}},
                "touchpoints": {"type": "array", "items": {"type": "string"},
                                "description": "Files/globs/modules this item affects, e.g. backend/app/routers/*. Powers related-work clustering."},
                "effort": {"type": "integer", "description": _EFFORT_DESC},
                "status": {"type": "string", "enum": _STATUS_ENUM, "description": "Defaults to backlog."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_item",
        "description": "Patch fields or advance status on an existing item. Returns the updated item.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "status": {"type": "string", "enum": _STATUS_ENUM},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "touchpoints": {"type": "array", "items": {"type": "string"},
                                "description": "Files/globs/modules this item affects (for related-work clustering)."},
                "effort": {"type": "integer", "description": _EFFORT_DESC},
                "blocker": {"type": "string", "description": "Free-text blocker; empty string clears it."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "search_items",
        "description": "Query the linear stream by free text (matches title, description, and tags), tags, and/or status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring matched against title, description, and tags."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Only items carrying at least one of these tags."},
                "status": {"type": "string", "enum": _STATUS_ENUM},
            },
        },
    },
    {
        "name": "add_memory",
        "description": "Attach a memory shard to an item or the global scope.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "scope": {"type": "string", "enum": ["global", "item"]},
                "item_id": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "search_memory",
        "description": "Semantic search over memory shards via pgvector cosine.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_backlog",
        "description": "Return prioritized backlog for planning.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "get_item_details",
        "description": "Full item incl. linked shards, blockers, deps.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "suggest_next",
        "description": "Rank the best next item from state + memory.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "link_items",
        "description": "Create a typed relationship between two items.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
                "type": {"type": "string", "enum": ["dependency", "code", "semantic", "tag"]},
                "reason": {"type": "string"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "extract_lessons",
        "description": "Auto-distill decisions/learnings from an item into memory.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "generate_digest",
        "description": "Compose a periodic progress digest across the project.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "related_work",
        "description": (
            "Items related to a given item by shared touchpoints (files/globs/modules it affects) "
            "and typed links, best-first — the code-neighborhood around a task. Read-only."
        ),
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "next_cluster",
        "description": (
            "Claim a whole code-neighborhood in one call: claims the best ready item plus its "
            "related ready items (up to max_items), all assigned to you. Returns the claimed batch "
            "(seed first). Use this to pull multiple related pieces of work simultaneously."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "max_items": {"type": "integer", "description": "Max items to claim in the cluster (default 3)."},
            },
        },
    },
    {
        "name": "claim_next",
        "description": (
            "Atomically claim the best ready item (unblocked backlog/next), assign it to you, and "
            "move it to in_progress. Two agents never get the same item — call this to pull work in "
            "a loop. Returns {claimed, item}; item is null when nothing is ready."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Who is claiming; defaults to this API key's name."},
                "lease_seconds": {"type": "integer", "description": "Lease length; a claim with no heartbeat within this window is reclaimable (default 600)."},
            },
        },
    },
    {
        "name": "heartbeat",
        "description": "Extend the lease on an item you've claimed so it isn't reclaimed while you work.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "agent_id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "release_item",
        "description": "Return a claimed item to the queue (e.g. you can't finish it); moves it back to `next` by default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "agent_id": {"type": "string"},
                "to_status": {"type": "string", "enum": items_svc.STATUSES},
            },
            "required": ["id"],
        },
    },
]

# Project-scoped tools accept an optional `project_id` that overrides the key's project.
_PROJECT_SCOPED = {
    "create_item", "search_items", "add_memory", "search_memory",
    "get_backlog", "suggest_next", "generate_digest", "link_items", "claim_next", "next_cluster",
}
# Creates accept an idempotency key so a retried call returns the original resource.
_IDEMPOTENT_CREATES = {"create_item", "add_memory", "link_items"}
# Paged reads accept limit + offset and return {results, total, limit, offset, has_more}.
_PAGED = {"search_items", "get_backlog"}
# Read-only tools never mutate state.
_READ_ONLY = {
    "get_context", "list_projects", "search_items", "search_memory",
    "get_backlog", "get_item_details", "suggest_next", "generate_digest", "related_work",
}

_PAGE_META = {  # shared output shape for paged reads (#9)
    "type": "object",
    "properties": {
        "results": {"type": "array"},
        "total": {"type": "integer"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        "has_more": {"type": "boolean"},
    },
}

# --- Output schemas (#8): every tool's structuredContent shape. ---
_STR = {"type": "string"}
_NULLABLE_STR = {"type": ["string", "null"]}
_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": _STR,
        "project_id": _NULLABLE_STR,
        "title": _STR,
        "status": {"type": "string", "enum": _STATUS_ENUM},
        "tags": {"type": "array", "items": _STR},
        "touchpoints": {"type": "array", "items": _STR},
        "effort": {"type": "integer"},
        "assignee": _STR,
        "claimed_by": _NULLABLE_STR,
    },
}
_SHARD_SCHEMA = {
    "type": "object",
    "properties": {
        "id": _STR, "text": _STR, "scope": _STR,
        "item_id": _NULLABLE_STR, "project_id": _NULLABLE_STR,
    },
}

_OUTPUT_SCHEMAS: dict[str, dict] = {
    "get_context": {
        "type": "object",
        "properties": {
            "project_id": _NULLABLE_STR,
            "project_name": _NULLABLE_STR,
            "key_project_id": _NULLABLE_STR,
            "scopes": {"type": "array", "items": _STR},
            "project_count": {"type": "integer"},
            "tool_count": {"type": "integer"},
        },
    },
    "list_projects": {
        "type": "object",
        "properties": {"results": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": _STR, "name": _STR, "accent": _STR, "description": _STR},
        }}},
    },
    "create_item": _ITEM_SCHEMA,
    "update_item": _ITEM_SCHEMA,
    "suggest_next": _ITEM_SCHEMA,  # or absent when the backlog is empty
    "add_memory": _SHARD_SCHEMA,
    "search_memory": {
        "type": "object",
        "properties": {
            "results": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "id": _STR, "text": _STR, "scope": _STR, "score": {"type": "number"},
                    "item_id": _NULLABLE_STR, "source": _STR, "project_id": _NULLABLE_STR,
                },
            }},
            "returned": {"type": "integer"},
            "top_k": {"type": "integer"},
        },
    },
    "get_item_details": {
        "type": "object",
        "properties": {
            "id": _STR, "title": _STR, "description": _STR,
            "status": {"type": "string", "enum": _STATUS_ENUM},
            "tags": {"type": "array", "items": _STR},
            "effort": {"type": "integer"}, "blocker": _STR,
            "pr": {"type": ["object", "null"]},
            "linked_shards": {"type": "array", "items": {"type": "object"}},
            "linked_requests": {"type": "array", "items": {"type": "object"}},
        },
    },
    "link_items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "a": _STR, "b": _STR, "type": _STR},
    },
    "extract_lessons": {
        "type": "object",
        "properties": {"results": {"type": "array", "items": {
            "type": "object", "properties": {"id": _STR, "text": _STR},
        }}},
    },
    "generate_digest": {
        "type": "object",
        "properties": {"digest": _STR},
    },
    "claim_next": {
        "type": "object",
        "properties": {"claimed": {"type": "boolean"}, "item": {"type": ["object", "null"]}},
    },
    "heartbeat": _ITEM_SCHEMA,
    "release_item": _ITEM_SCHEMA,
    "related_work": {"type": "object", "properties": {"results": {"type": "array"}}},
    "next_cluster": {
        "type": "object",
        "properties": {"claimed": {"type": "integer"}, "cluster": {"type": "array"}},
    },
}

for _t in TOOLS:
    _name = _t["name"]
    props = _t["inputSchema"].setdefault("properties", {})
    if _name in _PROJECT_SCOPED:
        props["project_id"] = {
            "type": "string",
            "description": "Override the key's project. Defaults to the API key's project.",
        }
    if _name in _IDEMPOTENT_CREATES:
        props["idempotency_key"] = {
            "type": "string",
            "description": "Opaque token; a repeat call with the same key returns the original resource.",
        }
    if _name in _PAGED:
        props["limit"] = {"type": "integer", "description": "Max results (default 25)."}
        props["offset"] = {"type": "integer", "description": "Results to skip for paging (default 0)."}
        _t["outputSchema"] = _PAGE_META
    elif _name in _OUTPUT_SCHEMAS:
        _t["outputSchema"] = _OUTPUT_SCHEMAS[_name]
    # MCP annotations so an agent can reason about safety (#7).
    _ro = _name in _READ_ONLY
    _t["annotations"] = {
        "readOnlyHint": _ro,
        "destructiveHint": _name == "update_item",
        # read-only + update_item are naturally idempotent; creates become idempotent with a key.
        "idempotentHint": _ro or _name in ({"update_item"} | _IDEMPOTENT_CREATES),
        "openWorldHint": False,
    }

LIVE_TOOL_COUNT = len(TOOLS)


def _item_dict(item) -> dict:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "title": item.title,
        "status": item.status,
        "tags": item.tags,
        "touchpoints": item.touchpoints or [],
        "effort": item.effort,
        "assignee": item.assignee,
        "claimed_by": item.claimed_by,
    }


def _shard_dict(shard) -> dict:
    return {
        "id": shard.id, "text": shard.text, "scope": shard.scope,
        "item_id": shard.item_id, "project_id": shard.project_id,
    }


def _paginate(rows: list, args: dict) -> dict:
    """Slice a full result list to a page and report totals (#9)."""
    limit = int(args.get("limit", 25))
    offset = int(args.get("offset", 0))
    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "results": page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }


def _idempotent_get(db: Session, args: dict, model) -> Any | None:
    """If the call carries an idempotency_key already seen, return the original resource."""
    prior = idem_svc.lookup(db, args.get("idempotency_key") or "")
    return db.get(model, prior.resource_id) if prior is not None else None


def _idempotent_remember(db: Session, args: dict, tool: str, resource_id: str) -> None:
    idem_svc.remember(db, args.get("idempotency_key") or "", tool, resource_id)


def _call_tool(db: Session, name: str, args: dict[str, Any], key: ApiKey) -> Any:
    # The key scopes the agent to a project; a per-call `project_id` argument overrides it.
    pid = args.get("project_id") or resolve_project_id(db, key.project_id)

    if name == "get_context":
        proj = db.get(Project, pid) if pid else None
        return {
            "project_id": pid,
            "project_name": proj.name if proj else None,
            "key_project_id": key.project_id,  # None => global key; agent should pass project_id
            "scopes": key.scopes,
            "project_count": db.scalar(select(func.count()).select_from(Project)),
            "tool_count": LIVE_TOOL_COUNT,
        }
    if name == "list_projects":
        return {"results": [
            {"id": p.id, "name": p.name, "accent": p.accent, "description": p.description}
            for p in db.scalars(select(Project).order_by(Project.name)).all()
        ]}
    if name == "create_item":
        cached = _idempotent_get(db, args, Item)
        if cached is not None:
            return _item_dict(cached)
        item = items_svc.create_item(
            db,
            title=args["title"],
            description=args.get("description", ""),
            tags=args.get("tags", []),
            effort=args.get("effort", 0),
            status=args.get("status", "backlog"),
            project_id=pid,
            touchpoints=args.get("touchpoints"),
            reporter={"name": "Agent", "handle": "mcp", "avatar": "#a78bfa"},
        )
        _idempotent_remember(db, args, "create_item", item.id)
        return _item_dict(item)
    if name == "update_item":
        item = items_svc.update_item(
            db,
            args["id"],
            status=args.get("status"),
            title=args.get("title"),
            description=args.get("description"),
            tags=args.get("tags"),
            effort=args.get("effort"),
            blocker=args.get("blocker"),
            touchpoints=args.get("touchpoints"),
        )
        if item is None:
            raise ValueError(f"item not found: {args['id']}")
        return _item_dict(item)
    if name == "search_items":
        rows = items_svc.search_items(
            db, args.get("query", ""), status=args.get("status"), project_id=pid,
            tags=args.get("tags"), limit=10_000,
        )
        return _paginate([_item_dict(i) for i in rows], args)
    if name == "add_memory":
        cached = _idempotent_get(db, args, MemoryShard)
        if cached is not None:
            return _shard_dict(cached)
        shard = mem_svc.add_memory(
            db,
            text_body=args["text"],
            scope=args.get("scope", "global"),
            item_id=args.get("item_id"),
            project_id=pid,
        )
        _idempotent_remember(db, args, "add_memory", shard.id)
        return _shard_dict(shard)
    if name == "search_memory":
        top_k = args.get("top_k", 5)
        hits = mem_svc.search_memory(db, args["query"], top_k=top_k, project_id=pid)
        results = [
            {
                "id": s.id, "text": s.text, "scope": s.scope, "score": round(score, 4),
                "item_id": s.item_id, "source": s.source, "project_id": s.project_id,
            }
            for s, score in hits
        ]
        return {"results": results, "returned": len(results), "top_k": top_k}
    if name == "get_backlog":
        rows = items_svc.get_backlog(db, limit=10_000, project_id=pid)
        return _paginate([_item_dict(i) for i in rows], args)
    if name == "get_item_details":
        details = items_svc.get_item_details(db, args["id"])
        if details is None:
            raise ValueError(f"item not found: {args['id']}")
        return details
    if name == "suggest_next":
        item = items_svc.suggest_next(db, project_id=pid)
        return _item_dict(item) if item else None
    if name == "related_work":
        item = db.get(Item, args["id"])
        if item is None:
            raise ValueError(f"item not found: {args['id']}")
        rel = cluster_svc.related_items(db, item, item.project_id)
        return {"results": [
            {**_item_dict(r["item"]), "score": r["score"], "shared": r["shared"], "link_types": r["link_types"]}
            for r in rel
        ]}
    if name == "next_cluster":
        agent = args.get("agent_id") or key.name or key.id
        batch = cluster_svc.next_cluster(db, agent, project_id=pid, max_items=args.get("max_items", 3))
        return {"claimed": len(batch), "cluster": [
            {**_item_dict(b["item"]), "seed": b["seed"], "shared": b["shared"], "link_types": b["link_types"]}
            for b in batch
        ]}
    if name == "link_items":
        cached = _idempotent_get(db, args, Link)
        if cached is not None:
            return {"id": cached.id, "a": cached.a, "b": cached.b, "type": cached.type}
        link = links_svc.create_link(
            db, a=args["a"], b=args["b"], type_=args.get("type", "dependency"),
            reason=args.get("reason", ""), project_id=pid,
        )
        _idempotent_remember(db, args, "link_items", link.id)
        return {"id": link.id, "a": link.a, "b": link.b, "type": link.type}
    if name == "claim_next":
        agent = args.get("agent_id") or key.name or key.id
        item = items_svc.claim_next(
            db, agent, project_id=pid,
            lease_seconds=args.get("lease_seconds", items_svc.DEFAULT_LEASE_SECONDS),
        )
        return {"claimed": item is not None, "item": _item_dict(item) if item else None}
    if name == "heartbeat":
        agent = args.get("agent_id") or key.name or key.id
        item = items_svc.heartbeat(db, args["id"], agent)
        if item is None:
            raise ValueError(f"not the lease holder, or unknown item: {args['id']}")
        return _item_dict(item)
    if name == "release_item":
        agent = args.get("agent_id") or key.name or key.id
        item = items_svc.release_item(db, args["id"], agent, to_status=args.get("to_status", "next"))
        if item is None:
            raise ValueError(f"not the lease holder, or unknown item: {args['id']}")
        return _item_dict(item)
    if name == "extract_lessons":
        return {"results": insights_svc.extract_lessons(db, args["id"])}
    if name == "generate_digest":
        return {"digest": insights_svc.generate_digest(db, project_id=pid)}
    raise ValueError(f"unknown tool: {name}")


def _rpc_result(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _rpc_error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _success(id_: Any, result: Any) -> dict:
    """Wrap a tool result. Objects are also returned as `structuredContent` (typed,
    no JSON-in-a-text-block); text mirrors it for back-compat (#8)."""
    payload: dict[str, Any] = {"content": [{"type": "text", "text": json.dumps(result)}]}
    if isinstance(result, dict):
        payload["structuredContent"] = result
    return _rpc_result(id_, payload)


def _tool_error(id_: Any, code: str, message: str) -> dict:
    """A tool-level failure. Reported via isError so the agent sees it, with a stable
    machine-readable `code` in structuredContent to branch on."""
    return _rpc_result(
        id_,
        {
            "content": [{"type": "text", "text": f"{code}: {message}"}],
            "structuredContent": {"error": {"code": code, "message": message}},
            "isError": True,
        },
    )


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(get_agent_key),
):
    body = await request.json()
    method = body.get("method")
    id_ = body.get("id")

    # Notifications (no id) get a 202 with no body.
    if method == "notifications/initialized":
        return Response(status_code=202)

    if method == "initialize":
        return _rpc_result(
            id_,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agentledger", "version": "0.1.0"},
            },
        )

    if method == "tools/list":
        return _rpc_result(id_, {"tools": TOOLS})

    if method == "tools/call":
        params = body.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        if name:
            mcp_stats.increment(db, name)  # per-tool metering for the MCP Tools page
        try:
            result = _call_tool(db, name, args, key)
        except (ValueError, KeyError) as e:
            # Bad input / not-found: the agent can read the message and correct itself.
            return _tool_error(id_, "invalid_request", str(e))
        except Exception:  # noqa: BLE001 — never leak a raw 500 to a JSON-RPC client
            logger.exception("MCP tool %r failed", name)
            db.rollback()
            return _tool_error(id_, "internal_error", f"internal error executing {name!r}")
        return _success(id_, result)

    return _rpc_error(id_, -32601, f"method not found: {method}")
