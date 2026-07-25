"""Assistant tool surface (AL-173).

The curated, safe set of operations the in-app assistant may call, wired to existing
service implementations (no new business logic). Each tool advertises a JSON-Schema the
tool-calling layer (AL-172) surfaces to the model; `dispatch` runs a `ToolCall` scoped to
the conversation's entity + project and gated by the caller's authz — an AI action can
never exceed what the user could do.

Writes execute here; the AL-177 approve/apply flow wraps `dispatch` (using `tool_kind`)
to STAGE a write as a proposed-action instead of running it. The registry makes adding
the remaining PRD tools (link_items, decompose_prd, grill-apply) a one-entry change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.providers.toolcall import ToolCall, ToolResult, ToolSpec
from app.security import authz
from app.services import items as items_svc
from app.services import memory as mem_svc
from app.services import prds as prd_svc

_STR = {"type": "string"}


@dataclass
class ToolContext:
    """Scoping for one assistant turn: who is asking, and about which entity."""
    db: Session
    user_id: str
    project_id: str
    entity_type: str  # item | prd
    entity_id: str


@dataclass(frozen=True)
class _Tool:
    spec: ToolSpec
    kind: str  # read | write
    handler: Callable[[ToolContext, dict], str]
    entity_types: tuple[str, ...] = ()  # empty = available for any thread


# ---- handlers (each reuses an existing service op; returns a compact result string) ----
def _get_item_details(ctx: ToolContext, inp: dict) -> str:
    item_id = inp.get("item_id") or (ctx.entity_id if ctx.entity_type == "item" else "")
    d = items_svc.get_item_details(ctx.db, item_id)
    return json.dumps(d, default=str) if d else f"item not found: {item_id}"


def _search_items(ctx: ToolContext, inp: dict) -> str:
    rows = items_svc.search_items(ctx.db, query=inp.get("query", ""), project_id=ctx.project_id)
    return json.dumps([{"id": i.id, "title": i.title, "status": i.status} for i in rows[:10]])


def _search_memory(ctx: ToolContext, inp: dict) -> str:
    hits = mem_svc.search_memory(ctx.db, inp.get("query", ""), project_id=ctx.project_id)
    return json.dumps([s.text for s, _ in hits])


def _update_item(ctx: ToolContext, inp: dict) -> str:
    # Scoped to the thread's item — the assistant can't retarget another item.
    fields = {k: inp[k] for k in ("status", "description", "effort") if k in inp}
    if not fields:
        return "no updatable fields provided (status | description | effort)"
    item = items_svc.update_item(ctx.db, ctx.entity_id, **fields)
    return f"updated {item.id}: {', '.join(fields)}" if item else f"item not found: {ctx.entity_id}"


def _create_item(ctx: ToolContext, inp: dict) -> str:
    title = (inp.get("title") or "").strip()
    if not title:
        return "title is required"
    item = items_svc.create_item(ctx.db, title=title, description=inp.get("description", ""),
                                 project_id=ctx.project_id)
    return f"created {item.id}: {item.title}"


def _update_prd(ctx: ToolContext, inp: dict) -> str:
    fields = {k: inp[k] for k in ("body", "status") if k in inp}
    if not fields:
        return "no updatable fields provided (body | status)"
    prd = prd_svc.update_prd(ctx.db, ctx.entity_id, **fields)
    return f"updated {prd.id}: {', '.join(fields)}" if prd else f"prd not found: {ctx.entity_id}"


def _add_memory(ctx: ToolContext, inp: dict) -> str:
    text = (inp.get("text") or "").strip()
    if not text:
        return "text is required"
    is_item = ctx.entity_type == "item"
    shard = mem_svc.add_memory(
        ctx.db, text_body=text, scope="item" if is_item else "global",
        item_id=ctx.entity_id if is_item else None, project_id=ctx.project_id,
        # enters as a candidate for human review (AL-49) — never straight into trusted memory
        status="candidate", origin="assistant", source=f"assistant: {ctx.entity_id}",
    )
    return f"proposed memory {shard.id} (candidate — needs review)"


_TOOLS: dict[str, _Tool] = {
    "get_item_details": _Tool(
        ToolSpec("get_item_details", "Read an item's full detail.",
                 {"type": "object", "properties": {"item_id": _STR}}),
        "read", _get_item_details),
    "search_items": _Tool(
        ToolSpec("search_items", "Search this project's items by free text.",
                 {"type": "object", "properties": {"query": _STR}, "required": ["query"]}),
        "read", _search_items),
    "search_memory": _Tool(
        ToolSpec("search_memory", "Semantic search over this project's published memory.",
                 {"type": "object", "properties": {"query": _STR}, "required": ["query"]}),
        "read", _search_memory),
    "update_item": _Tool(
        ToolSpec("update_item", "Update THIS item's status, description, or effort.",
                 {"type": "object", "properties": {
                     "status": _STR, "description": _STR, "effort": {"type": "integer"}}}),
        "write", _update_item, entity_types=("item",)),
    "create_item": _Tool(
        ToolSpec("create_item", "Create a new backlog item in this project.",
                 {"type": "object", "properties": {"title": _STR, "description": _STR},
                  "required": ["title"]}),
        "write", _create_item),
    "update_prd": _Tool(
        ToolSpec("update_prd", "Update THIS PRD's body or status.",
                 {"type": "object", "properties": {"body": _STR, "status": _STR}}),
        "write", _update_prd, entity_types=("prd",)),
    "add_memory": _Tool(
        ToolSpec("add_memory", "Propose a memory shard (enters review as a candidate).",
                 {"type": "object", "properties": {"text": _STR}, "required": ["text"]}),
        "write", _add_memory),
}


def available_tools(ctx: ToolContext) -> list[ToolSpec]:
    """The tools applicable to this thread's entity type (e.g. update_prd only on a PRD
    thread), for advertising to the model."""
    return [t.spec for t in _TOOLS.values() if not t.entity_types or ctx.entity_type in t.entity_types]


def tool_kind(name: str) -> str | None:
    """`read` | `write` | None — the seam AL-177 uses to gate writes behind approval."""
    tool = _TOOLS.get(name)
    return tool.kind if tool else None


def dispatch(ctx: ToolContext, call: ToolCall) -> ToolResult:
    """Run a tool call, scoped + authz-gated. Never raises — failures come back as an
    `is_error` result so the model can self-correct."""
    tool = _TOOLS.get(call.name)
    if tool is None:
        return ToolResult(id=call.id, content=f"unknown tool: {call.name}", is_error=True)
    if tool.entity_types and ctx.entity_type not in tool.entity_types:
        return ToolResult(id=call.id, is_error=True,
                          content=f"{call.name} is not available on a {ctx.entity_type} thread")
    permitted = (authz.can_write if tool.kind == "write" else authz.can_read)(
        ctx.db, ctx.user_id, ctx.project_id)
    if not permitted:
        return ToolResult(id=call.id, is_error=True,
                          content=f"not authorized to {tool.kind} in this project")
    try:
        return ToolResult(id=call.id, content=tool.handler(ctx, call.input or {}))
    except Exception as e:  # noqa: BLE001 — surface as a tool error, never crash the loop
        return ToolResult(id=call.id, content=f"error: {e}", is_error=True)
