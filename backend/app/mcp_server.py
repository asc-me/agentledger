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
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey
from app.security.deps import get_agent_key
from app.services import insights as insights_svc
from app.services import items as items_svc
from app.services import links as links_svc
from app.services import mcp_stats
from app.services import memory as mem_svc
from app.services.projects import resolve_project_id

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSION = "2025-06-18"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_item",
        "description": "Create a tracker item with title, description, tags, effort.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "effort": {"type": "integer"},
                "status": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_item",
        "description": "Patch fields or advance status on an existing item.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "status": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "blocker": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "search_items",
        "description": "Query the linear stream by text, tag, or status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "status": {"type": "string"},
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
]

# Project-scoped tools accept an optional `project_id` that overrides the key's project.
_PROJECT_SCOPED = {
    "create_item", "search_items", "add_memory", "search_memory",
    "get_backlog", "suggest_next", "generate_digest",
}
for _t in TOOLS:
    if _t["name"] in _PROJECT_SCOPED:
        _t["inputSchema"].setdefault("properties", {})["project_id"] = {
            "type": "string",
            "description": "Override the key's project. Defaults to the API key's project.",
        }

LIVE_TOOL_COUNT = len(TOOLS)


def _item_dict(item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "tags": item.tags,
        "effort": item.effort,
    }


def _call_tool(db: Session, name: str, args: dict[str, Any], project_id: str | None = None) -> Any:
    # The key scopes the agent to a project; a per-call `project_id` argument overrides it.
    pid = args.get("project_id") or project_id
    if name == "create_item":
        item = items_svc.create_item(
            db,
            title=args["title"],
            description=args.get("description", ""),
            tags=args.get("tags", []),
            effort=args.get("effort", 0),
            status=args.get("status", "backlog"),
            project_id=pid,
            reporter={"name": "Agent", "handle": "mcp", "avatar": "#a78bfa"},
        )
        return _item_dict(item)
    if name == "update_item":
        item = items_svc.update_item(
            db,
            args["id"],
            status=args.get("status"),
            title=args.get("title"),
            description=args.get("description"),
            blocker=args.get("blocker"),
        )
        if item is None:
            raise ValueError(f"item not found: {args['id']}")
        return _item_dict(item)
    if name == "search_items":
        rows = items_svc.search_items(db, args.get("query", ""), status=args.get("status"), project_id=pid)
        return [_item_dict(i) for i in rows]
    if name == "add_memory":
        shard = mem_svc.add_memory(
            db,
            text_body=args["text"],
            scope=args.get("scope", "global"),
            item_id=args.get("item_id"),
            project_id=pid,
        )
        return {"id": shard.id, "text": shard.text, "scope": shard.scope}
    if name == "search_memory":
        hits = mem_svc.search_memory(db, args["query"], top_k=args.get("top_k", 5), project_id=pid)
        return [
            {"id": s.id, "text": s.text, "scope": s.scope, "score": round(score, 4)}
            for s, score in hits
        ]
    if name == "get_backlog":
        return [_item_dict(i) for i in items_svc.get_backlog(db, limit=args.get("limit", 20), project_id=pid)]
    if name == "get_item_details":
        details = items_svc.get_item_details(db, args["id"])
        if details is None:
            raise ValueError(f"item not found: {args['id']}")
        return details
    if name == "suggest_next":
        item = items_svc.suggest_next(db, project_id=pid)
        return _item_dict(item) if item else None
    if name == "link_items":
        link = links_svc.create_link(
            db, a=args["a"], b=args["b"], type_=args.get("type", "dependency"),
            reason=args.get("reason", ""),
        )
        return {"id": link.id, "a": link.a, "b": link.b, "type": link.type}
    if name == "extract_lessons":
        return insights_svc.extract_lessons(db, args["id"])
    if name == "generate_digest":
        return {"digest": insights_svc.generate_digest(db, project_id=pid)}
    raise ValueError(f"unknown tool: {name}")


def _rpc_result(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _rpc_error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


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
            project_id = resolve_project_id(db, key.project_id)
            result = _call_tool(db, name, args, project_id)
        except (ValueError, KeyError) as e:
            return _rpc_result(
                id_,
                {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True},
            )
        return _rpc_result(
            id_,
            {"content": [{"type": "text", "text": json.dumps(result)}]},
        )

    return _rpc_error(id_, -32601, f"method not found: {method}")
