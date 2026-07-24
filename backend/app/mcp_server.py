"""MCP endpoint (JSON-RPC 2.0 over HTTP).

Exposes the live AgentLedger tools to agents, authenticated by a scoped API key
(the count is `LIVE_TOOL_COUNT`, derived from `TOOLS` — never hardcode it).
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
from starlette.concurrency import run_in_threadpool
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import errors
from app.db import get_db
from app.models import ApiKey, Item, Link, MemoryShard, Project
from app.security import authz
from app.security.deps import get_agent_key
from app.services import clustering as cluster_svc
from app.services import code_graph as code_svc
from app.services import events as events_svc
from app.services import idempotency as idem_svc
from app.services import insights as insights_svc
from app.services import items as items_svc
from app.services import links as links_svc
from app.services import mcp_stats
from app.services import memory as mem_svc
from app.services import quotas
from app.services import prds as prd_svc
from app.services import prioritization as prio_svc
from app.services import requests as req_svc
from app.services import upstream as up_svc

import httpx

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSION = "2025-06-18"

logger = logging.getLogger("agentledger.mcp")

_STATUS_ENUM = items_svc.STATUSES
_FIDELITY_ENUM = items_svc.FIDELITIES
_LINK_TYPE_ENUM = links_svc.LINK_TYPES
_REQUEST_TYPE_ENUM = req_svc.REQUEST_TYPES
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
                "fidelity": {"type": "string", "enum": _FIDELITY_ENUM,
                             "description": "`low` (specifiable now) or `high` (needs a prototype first). Defaults to low."},
                "prd_id": {"type": "string", "description": "The PRD this task implements (traceability)."},
                "prd_section": {"type": "string", "description": "The PRD section this task implements."},
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
                "fidelity": {"type": "string", "enum": _FIDELITY_ENUM,
                             "description": "`low` or `high` (needs a prototype first)."},
                "prd_id": {"type": "string"},
                "prd_section": {"type": "string"},
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
        "description": (
            "Record a memory shard (a decision, lesson, or note) on an item or the global scope. "
            "Agent-written shards enter as a `candidate` — a human reviews and publishes them "
            "before they surface in the default search, so an unverified note can't become ground "
            "truth for future agents. Returns the shard incl. its `status`."
        ),
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
        "description": (
            "Recall relevant past context before you act: semantic (meaning-based) search over "
            "memory shards. Returns published (human-reviewed) shards ranked by similarity with a "
            "score and `status`. Set `include_candidates: true` to also see unreviewed agent notes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "include_candidates": {
                    "type": "boolean",
                    "description": "Also return unpublished candidate shards (default false).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_backlog",
        "description": (
            "Prioritized backlog for planning: backlog/next items ranked ready-first then by a "
            "composite score (status, unblocks-many, request votes, effort, staleness). Each item "
            "carries `ready`, `blocked_by` (unfinished deps), `unblocks`, `votes`, `score`."
        ),
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "get_item_details",
        "description": (
            "The full record for one item — the only tool that returns its description, blockers, "
            "dependencies, and linked memory shards. Call it after search_items/get_backlog to read "
            "everything before working an item."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "suggest_next",
        "description": (
            "Advisory: the single best next item to work, ranked from backlog state + memory, "
            "WITHOUT claiming it (unlike claim_next, which atomically locks work for a loop). "
            "Returns {item} — item is null when nothing is ready. Use for planning; use claim_next to execute."
        ),
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
                "type": {"type": "string", "enum": _LINK_TYPE_ENUM},
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
        "name": "prd_coverage",
        "description": (
            "Spec-to-task rollup for a PRD: per-section task counts by status, coverage %, and "
            "`gaps` (sections with no tasks yet). Read-only."
        ),
        "inputSchema": {"type": "object", "properties": {"prd_id": {"type": "string"}}, "required": ["prd_id"]},
    },
    {
        "name": "decompose_prd",
        "description": (
            "Propose one tracked task per un-covered PRD section (the gaps). With create=true, "
            "creates them as backlog items linked to the PRD + section — the spec drives the tracker. "
            "Framing sections (Problem, Goals, Non-goals, Success criteria, …) are skipped: they "
            "describe the work rather than being work."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prd_id": {"type": "string"},
                "create": {"type": "boolean", "description": "Create the proposed tasks (default false = dry-run)."},
                "include_prose": {
                    "type": "boolean",
                    "description": "Also propose tasks for framing sections (default false).",
                },
            },
            "required": ["prd_id"],
        },
    },
    {
        "name": "create_prd",
        "description": (
            "Author a PRD (the durable handoff artifact). Use `## ` markdown headings for sections — "
            "decompose_prd turns each into tracked work and prd_coverage tracks it. Pass `body` for a "
            "full markdown draft, or `template` (standard|blank) for a skeleton. Returns the PRD incl. id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string", "description": "Full markdown draft (wins over template). Use `## ` section headings."},
                "template": {"type": "string", "enum": ["standard", "blank"], "description": "Skeleton when no body (default standard)."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_prd",
        "description": (
            "Patch a PRD's title, status (draft|review|approved), or body (full markdown replace). "
            "Returns the updated PRD. To keep a history checkpoint, the UI snapshots versions; edits here "
            "update the working draft."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prd_id": {"type": "string"},
                "title": {"type": "string"},
                "status": {"type": "string", "enum": ["draft", "review", "approved"]},
                "body": {"type": "string", "description": "Full markdown body (replaces the current draft)."},
            },
            "required": ["prd_id"],
        },
    },
    {
        "name": "grill_prd",
        "description": (
            "Get the next batch of relentless clarifying questions to sharpen a PRD before building "
            "(the 'grill' technique). Surfaces unstated assumptions, scope boundaries, failure modes, and "
            "open decisions — favoring low-fidelity questions answerable in words over high-fidelity ones "
            "that need a prototype. Returns a markdown question list. Read-only; author answers by "
            "update_prd."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"prd_id": {"type": "string"}},
            "required": ["prd_id"],
        },
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
    {
        "name": "describe_code",
        "description": (
            "Record the codebase's structure and relations as a queryable graph. You (the "
            "coding agent) have the repo in context, so you are the source of truth: upsert "
            "`nodes` (module/file/symbol, each with a one-paragraph summary of what it is and "
            "owns) and `edges` (imports/calls/owns/tested_by/references between paths). "
            "Idempotent per path — re-describe a file after you change it, passing its new "
            "`content_hash`, to keep the map fresh. Pass `prune=true` when you've described a "
            "whole subtree to mark nodes you no longer saw as stale."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "nodes": {
                    "type": "array",
                    "description": "Code units to upsert.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Repo-relative, e.g. app/services/items.py or app/services/items.py::create_item"},
                            "kind": {"type": "string", "enum": code_svc.NODE_KINDS, "description": "module | file | symbol (default file)."},
                            "name": {"type": "string", "description": "Short label, e.g. the module or symbol name."},
                            "lang": {"type": "string", "description": "python | ts | ... (optional)."},
                            "summary": {"type": "string", "description": "One paragraph: what it is, does, and owns."},
                            "content_hash": {"type": "string", "description": "Hash of the source (e.g. git blob sha) — powers staleness."},
                        },
                        "required": ["path"],
                    },
                },
                "edges": {
                    "type": "array",
                    "description": "Directed, typed relations between paths. A dst need not be a described node yet.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "src": {"type": "string"},
                            "dst": {"type": "string"},
                            "type": {"type": "string", "enum": code_svc.EDGE_TYPES},
                        },
                        "required": ["src", "dst"],
                    },
                },
                "prune": {"type": "boolean", "description": "Mark project nodes absent from this batch as stale (default false)."},
            },
        },
    },
    {
        "name": "get_code_map",
        "description": (
            "The project's code graph: every described node (path, kind, summary, fresh) and the "
            "typed edges between them. Optionally filter by `kind`. Read-only — the map an agent "
            "or the connected LLM reads to understand the codebase without a checkout."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": code_svc.NODE_KINDS}},
        },
    },
    {
        "name": "code_neighbors",
        "description": (
            "The neighborhood around a code path: outgoing and incoming edges grouped by type, "
            "plus the work items whose touchpoints touch it. Answers 'what depends on this / what "
            "does it depend on / what work touches it'. Read-only; works even for a path that "
            "isn't a described node yet (shows what points at it)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": "Semantic search over code-node summaries (pgvector cosine). Returns ranked nodes with scores.",
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
        "name": "link_code",
        "description": (
            "Bridge a tracker item OR request to a code path — the explicit, typed link between "
            "the work (idea/bug/feature) and the code graph. Use when a bug affects a module, a "
            "feature implements one, or a test covers it. `ref_id` is an item id (AL-12) or "
            "request id (R-31); the type is inferred. Idempotent. Surfaces both ways: on the "
            "code node (code_neighbors) and on the item/request."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref_id": {"type": "string", "description": "Item id (e.g. AL-12) or request id (e.g. R-31)."},
                "path": {"type": "string", "description": "Code path to link to (need not be a described node yet)."},
                "relation": {"type": "string", "enum": code_svc.REF_RELATIONS, "description": "Defaults to affects."},
                "ref_type": {"type": "string", "enum": code_svc.REF_TYPES, "description": "Usually inferred from the id; set to disambiguate."},
            },
            "required": ["ref_id", "path"],
        },
    },
    {
        "name": "unlink_code",
        "description": "Remove links from an item/request to a code path. Omit `relation` to remove all relations for that pair.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref_id": {"type": "string"},
                "path": {"type": "string"},
                "relation": {"type": "string", "enum": code_svc.REF_RELATIONS},
            },
            "required": ["ref_id", "path"],
        },
    },
    {
        "name": "report_agentledger_issue",
        "description": (
            "Report a bug or idea about AgentLedger ITSELF (the tool you're using), not about the "
            "project you're working on. Sends it upstream to AgentLedger's maintainers — use when "
            "you hit a limitation, a broken tool, or think of an improvement to AgentLedger. "
            "Deduped on arrival. Returns the created upstream request id (or matched duplicates)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": _REQUEST_TYPE_ENUM, "description": "Defaults to feedback."},
                "title": {"type": "string"},
                "detail": {"type": "string", "description": "What happened / what you'd want. Include repro if it's a bug."},
            },
            "required": ["title"],
        },
    },
]

# Project-scoped tools accept an optional `project_id` that overrides the key's project.
_PROJECT_SCOPED = {
    "create_item", "search_items", "add_memory", "search_memory",
    "get_backlog", "suggest_next", "generate_digest", "link_items", "claim_next", "next_cluster",
    "describe_code", "get_code_map", "code_neighbors", "search_code",
    "link_code", "unlink_code", "create_prd",
}
# Creates accept an idempotency key so a retried call returns the original resource.
_IDEMPOTENT_CREATES = {"create_item", "add_memory", "link_items"}
# Writes that are idempotent by their own natural key (no idempotency token needed).
_IDEMPOTENT_WRITES = {"describe_code", "link_code"}
# Paged reads accept limit + offset and return {results, total, limit, offset, has_more}.
_PAGED = {"search_items", "get_backlog"}
# Write tools whose target is a tracker item (for audit target_type labeling).
_ITEM_WRITE_TOOLS = {"create_item", "update_item", "claim_next", "heartbeat", "release_item"}
# Read-only tools never mutate state.
_READ_ONLY = {
    "get_context", "list_projects", "search_items", "search_memory",
    "get_backlog", "get_item_details", "suggest_next", "generate_digest", "related_work",
    "prd_coverage", "grill_prd", "get_code_map", "code_neighbors", "search_code",
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
        "prd_id": _NULLABLE_STR,
        "prd_section": _STR,
        "fidelity": {"type": "string", "enum": _FIDELITY_ENUM},
    },
}
_SHARD_SCHEMA = {
    "type": "object",
    "properties": {
        "id": _STR, "text": _STR, "scope": _STR,
        "item_id": _NULLABLE_STR, "project_id": _NULLABLE_STR, "status": _STR,
    },
}

_PRD_SCHEMA_REF = {
    "type": "object",
    "properties": {
        "id": _STR, "project_id": _NULLABLE_STR, "title": _STR, "status": _STR,
        "version": _STR, "sections": {"type": "array", "items": _STR},
        "linked": {"type": "array", "items": _STR}, "body": _STR,
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
    "suggest_next": {  # stable {item: <item|null>} wrapper — never a bare null
        "type": "object",
        "properties": {"item": {**_ITEM_SCHEMA, "type": ["object", "null"]}},
    },
    "add_memory": _SHARD_SCHEMA,
    "search_memory": {
        "type": "object",
        "properties": {
            "results": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "id": _STR, "text": _STR, "scope": _STR, "score": {"type": "number"},
                    "item_id": _NULLABLE_STR, "source": _STR, "project_id": _NULLABLE_STR, "status": _STR,
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
    "prd_coverage": {
        "type": "object",
        "properties": {
            "prd_id": _STR, "sections": {"type": "array"}, "gaps": {"type": "array"},
            "total_items": {"type": "integer"}, "done_items": {"type": "integer"},
            "percent_done": {"type": "integer"},
        },
    },
    "decompose_prd": {
        "type": "object",
        "properties": {"prd_id": _STR, "proposals": {"type": "array"}, "created": {"type": "array"}},
    },
    "create_prd": _PRD_SCHEMA_REF,
    "update_prd": _PRD_SCHEMA_REF,
    "grill_prd": {
        "type": "object",
        "properties": {"prd_id": _STR, "questions": _STR},
    },
    "describe_code": {
        "type": "object",
        "properties": {
            "nodes_upserted": {"type": "integer"},
            "edges_upserted": {"type": "integer"},
            "marked_stale": {"type": "integer"},
            "upserted_paths": {"type": "array", "items": _STR},
            "stale_paths": {"type": "array", "items": _STR},
        },
    },
    "get_code_map": {
        "type": "object",
        "properties": {
            "nodes": {"type": "array"}, "edges": {"type": "array"},
            "node_count": {"type": "integer"}, "edge_count": {"type": "integer"},
        },
    },
    "code_neighbors": {
        "type": "object",
        "properties": {
            "path": _STR, "node": {"type": ["object", "null"]},
            "outgoing": {"type": "array"}, "incoming": {"type": "array"},
            "items_touching": {"type": "array"},
            "linked_items": {"type": "array"}, "linked_requests": {"type": "array"},
        },
    },
    "search_code": {
        "type": "object",
        "properties": {
            "results": {"type": "array"}, "returned": {"type": "integer"}, "top_k": {"type": "integer"},
        },
    },
    "link_code": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"}, "ref_type": _STR, "ref_id": _STR, "path": _STR, "relation": _STR,
        },
    },
    "unlink_code": {
        "type": "object",
        "properties": {"removed": {"type": "integer"}},
    },
    "report_agentledger_issue": {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"}, "request_id": _NULLABLE_STR,
            "target": _STR, "duplicates": {"type": "array"},
        },
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
        "idempotentHint": _ro or _name in ({"update_item"} | _IDEMPOTENT_CREATES | _IDEMPOTENT_WRITES),
        "openWorldHint": False,
    }

LIVE_TOOL_COUNT = len(TOOLS)
_SCHEMA_BY_NAME: dict[str, dict] = {t["name"]: t["inputSchema"] for t in TOOLS}

# JSON-schema primitive -> (python type, label). bool is excluded from int on purpose.
_JSON_TYPES: dict[str, tuple[type | tuple[type, ...], str]] = {
    "string": (str, "a string"),
    "integer": (int, "an integer"),
    "array": (list, "an array"),
    "boolean": (bool, "a boolean"),
    "object": (dict, "an object"),
}


def _validate_args(name: str, args: dict[str, Any]) -> None:
    """Check args against the tool's declared inputSchema BEFORE dispatch, so a
    bad call becomes an actionable `validation` error instead of a KeyError or a
    silently-accepted junk value (AL-47). Required fields, enums, and primitive
    types only — deliberately lightweight, no external validator dependency."""
    schema = _SCHEMA_BY_NAME.get(name)
    if schema is None:
        return  # unknown tool handled by the dispatcher
    props: dict = schema.get("properties", {})
    required: list = schema.get("required", [])

    missing = [f for f in required if args.get(f) in (None, "")]
    if missing:
        raise errors.Validation(
            f"{name!r} is missing required argument{'s' if len(missing) > 1 else ''}: "
            f"{', '.join(missing)}",
            hint=f"required: {', '.join(required)}",
        )

    for field, value in args.items():
        spec = props.get(field)
        if not spec or value is None:
            continue  # unknown extras are ignored; None means "absent"
        enum = spec.get("enum")
        if enum is not None and value not in enum:
            raise errors.Validation(
                f"invalid {field}: {value!r}",
                hint=f"allowed values: {', '.join(map(str, enum))}",
            )
        expected = spec.get("type")
        if expected in _JSON_TYPES:
            py_type, label = _JSON_TYPES[expected]
            ok = isinstance(value, py_type) and not (expected == "integer" and isinstance(value, bool))
            if not ok:
                raise errors.Validation(
                    f"{field} must be {label}", hint=f"got {type(value).__name__}"
                )


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
        "prd_id": item.prd_id,
        "prd_section": item.prd_section,
        "fidelity": item.fidelity,
    }


def _shard_dict(shard) -> dict:
    return {
        "id": shard.id, "text": shard.text, "scope": shard.scope,
        "item_id": shard.item_id, "project_id": shard.project_id,
        "status": shard.status,
    }


def _prd_dict(prd) -> dict:
    return {
        "id": prd.id,
        "project_id": prd.project_id,
        "title": prd.title,
        "status": prd.status,
        "version": prd.version,
        "sections": prd_svc.parse_sections(prd.body),  # the `## ` headings, in order
        "linked": list(prd.linked or []),
        "body": prd.body,
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


def _idempotent_get(db: Session, args: dict, tool: str, model) -> Any | None:
    """If the call carries an idempotency_key already seen, return the original
    resource. A key remembered for a DIFFERENT tool is a conflict, not a silent
    duplicate (AL-47) — the agent reused a token across logical operations."""
    prior = idem_svc.lookup(db, args.get("idempotency_key") or "")
    if prior is None:
        return None
    if prior.tool != tool:
        raise errors.Conflict(
            f"idempotency_key was already used for {prior.tool!r}, not {tool!r}",
            hint="use a fresh idempotency_key for each distinct create",
        )
    return db.get(model, prior.resource_id)


def _idempotent_remember(db: Session, args: dict, tool: str, resource_id: str) -> None:
    idem_svc.remember(db, args.get("idempotency_key") or "", tool, resource_id)


def _scoped_item(db: Session, item_id: str, scope_ids: list[str]) -> Item:
    """Load an item and require it inside the key's project scope. The refusal
    deliberately does not reveal which project an off-scope item belongs to."""
    item = db.get(Item, item_id)
    if item is None:
        raise errors.NotFound(f"item not found: {item_id}", hint="use search_items to find a valid id")
    if item.project_id not in scope_ids:
        raise authz.Forbidden(f"item {item_id!r} is outside this key's project scope")
    return item


def _call_tool(db: Session, name: str, args: dict[str, Any], key: ApiKey) -> Any:
    # Authority: a key's declared scopes ∩ its owner's memberships bound every call
    # (a key never out-ranks the user who minted it). `project_id` args can select
    # among in-scope projects but can no longer escape the scope.
    writes = name not in _READ_ONLY
    if writes and "write" not in (key.scopes or []):
        raise authz.Forbidden(
            f"api key {key.name!r} has scopes {key.scopes} but {name!r} mutates state; "
            "mint a key with the 'write' scope or use a read-only tool"
        )
    readable = authz.key_readable_ids(db, key)
    allowed = authz.key_writable_ids(db, key) if writes else readable
    requested = args.get("project_id")
    if requested and requested not in allowed:
        raise authz.Forbidden(
            f"project {requested!r} is outside this key's {'write' if writes else 'read'} scope "
            f"(in scope: {', '.join(allowed) or 'none'})"
        )
    pid = (
        requested
        or (key.project_id if key.project_id in allowed else None)
        or (allowed[0] if allowed else None)
    )
    if pid is None and name in _PROJECT_SCOPED:
        raise authz.Forbidden(
            f"no project in scope for {name!r}: the key's owner has no "
            f"{'write-access ' if writes else ''}project memberships; "
            "ask a project owner to grant access"
        )

    # Rate/quota gates (hosted only; attributed to the org owning the target project;
    # calls with no project in scope are exempt). Burst cap first — it's the cheap
    # check that protects the monthly counter's DB write under a flood — then meter the
    # call against the org's monthly plan allowance.
    _org_id = quotas.org_id_for_project(db, pid)
    quotas.enforce_org_rate(_org_id)
    quotas.meter_call(db, _org_id)

    if name == "get_context":
        proj = db.get(Project, pid) if pid else None
        return {
            "project_id": pid,
            "project_name": proj.name if proj else None,
            "key_project_id": key.project_id,  # None => global key; agent should pass project_id
            "scopes": key.scopes,
            "readable_projects": readable,
            "writable_projects": authz.key_writable_ids(db, key),
            "project_count": db.scalar(select(func.count()).select_from(Project)),
            "tool_count": LIVE_TOOL_COUNT,
        }
    if name == "list_projects":
        return {"results": [
            {"id": p.id, "name": p.name, "accent": p.accent, "description": p.description}
            for p in db.scalars(select(Project).order_by(Project.name)).all()
            if p.id in readable
        ]}
    if name == "create_item":
        cached = _idempotent_get(db, args, "create_item", Item)
        if cached is not None:
            return _item_dict(cached)
        item = items_svc.create_item(
            db,
            title=args["title"],
            description=args.get("description", ""),
            tags=args.get("tags", []),
            effort=args.get("effort", 0),
            status=args.get("status", "backlog"),
            fidelity=args.get("fidelity", "low"),
            project_id=pid,
            touchpoints=args.get("touchpoints"),
            prd_id=args.get("prd_id"),
            prd_section=args.get("prd_section", ""),
            reporter={"name": "Agent", "handle": "mcp", "avatar": "#a78bfa"},
        )
        _idempotent_remember(db, args, "create_item", item.id)
        return _item_dict(item)
    if name == "update_item":
        _scoped_item(db, args["id"], allowed)
        item = items_svc.update_item(
            db,
            args["id"],
            status=args.get("status"),
            title=args.get("title"),
            description=args.get("description"),
            tags=args.get("tags"),
            effort=args.get("effort"),
            blocker=args.get("blocker"),
            fidelity=args.get("fidelity"),
            touchpoints=args.get("touchpoints"),
            prd_id=args.get("prd_id"),
            prd_section=args.get("prd_section"),
        )
        if item is None:
            raise errors.NotFound(f"item not found: {args['id']}")
        return _item_dict(item)
    if name == "search_items":
        rows = items_svc.search_items(
            db, args.get("query", ""), status=args.get("status"), project_id=pid,
            tags=args.get("tags"), limit=10_000,
        )
        return _paginate([_item_dict(i) for i in rows], args)
    if name == "add_memory":
        cached = _idempotent_get(db, args, "add_memory", MemoryShard)
        if cached is not None:
            return _shard_dict(cached)
        if args.get("item_id"):
            _scoped_item(db, args["item_id"], allowed)
        quotas.enforce_shard_quota(db, quotas.org_id_for_project(db, pid))
        # Agent-written memory enters as a CANDIDATE — it reaches the trusted
        # retrieval path only after a human publishes it (AL-49).
        shard = mem_svc.add_memory(
            db,
            text_body=args["text"],
            scope=args.get("scope", "global"),
            item_id=args.get("item_id"),
            project_id=pid,
            status="candidate",
            origin=f"agent:{key.name or key.id}",
        )
        _idempotent_remember(db, args, "add_memory", shard.id)
        return _shard_dict(shard)
    if name == "search_memory":
        top_k = args.get("top_k", 5)
        hits = mem_svc.search_memory(
            db, args["query"], top_k=top_k, project_id=pid,
            include_candidates=bool(args.get("include_candidates", False)),
        )
        results = [
            {
                "id": s.id, "text": s.text, "scope": s.scope, "score": round(score, 4),
                "item_id": s.item_id, "source": s.source, "project_id": s.project_id,
                "status": s.status,
            }
            for s, score in hits
        ]
        return {"results": results, "returned": len(results), "top_k": top_k}
    if name == "get_backlog":
        ranked = prio_svc.prioritized(db, pid, statuses=("backlog", "next"), include_blocked=True)
        rows = [
            {**_item_dict(r["item"]), "ready": r["ready"], "blocked_by": r["blocked_by"],
             "unblocks": r["unblocks"], "votes": r["votes"], "score": r["score"]}
            for r in ranked
        ]
        return _paginate(rows, args)
    if name == "get_item_details":
        _scoped_item(db, args["id"], readable)
        details = items_svc.get_item_details(db, args["id"])
        if details is None:
            raise errors.NotFound(f"item not found: {args['id']}")
        return details
    if name == "suggest_next":
        item = items_svc.suggest_next(db, project_id=pid)
        # Stable shape whether or not the backlog has a candidate (parallels
        # claim_next's {claimed, item}) — never a bare null (AL-47).
        return {"item": _item_dict(item) if item else None}
    if name == "related_work":
        item = _scoped_item(db, args["id"], readable)
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
        cached = _idempotent_get(db, args, "link_items", Link)
        if cached is not None:
            return {"id": cached.id, "a": cached.a, "b": cached.b, "type": cached.type}
        # Both endpoints must exist and be in scope — also stops dangling links
        # from poisoning get_backlog's blocked_by.
        _scoped_item(db, args["a"], allowed)
        _scoped_item(db, args["b"], allowed)
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
        _scoped_item(db, args["id"], allowed)  # raises the precise error first
        agent = args.get("agent_id") or key.name or key.id
        item = items_svc.heartbeat(db, args["id"], agent)
        if item is None:
            raise errors.Conflict(
                f"not the lease holder for {args['id']!r}",
                hint="another agent holds the lease; claim_next for fresh work",
            )
        return _item_dict(item)
    if name == "release_item":
        _scoped_item(db, args["id"], allowed)
        agent = args.get("agent_id") or key.name or key.id
        item = items_svc.release_item(db, args["id"], agent, to_status=args.get("to_status", "next"))
        if item is None:
            raise errors.Conflict(
                f"not the lease holder for {args['id']!r}",
                hint="the lease expired or another agent holds it",
            )
        return _item_dict(item)
    if name == "extract_lessons":
        _scoped_item(db, args["id"], allowed)
        return {"results": insights_svc.extract_lessons(db, args["id"])}
    if name == "generate_digest":
        return {"digest": insights_svc.generate_digest(db, project_id=pid)}
    if name == "prd_coverage":
        prd = prd_svc.get_prd(db, args["prd_id"])
        if prd is None:
            raise errors.NotFound(f"prd not found: {args['prd_id']}")
        if prd.project_id not in readable:
            raise authz.Forbidden(f"prd {args['prd_id']!r} is outside this key's project scope")
        return prd_svc.coverage(db, prd)
    if name == "decompose_prd":
        prd = prd_svc.get_prd(db, args["prd_id"])
        if prd is None:
            raise errors.NotFound(f"prd not found: {args['prd_id']}")
        if prd.project_id not in allowed:
            raise authz.Forbidden(f"prd {args['prd_id']!r} is outside this key's project scope")
        return prd_svc.decompose(
            db, prd,
            create=bool(args.get("create", False)),
            include_prose=bool(args.get("include_prose", False)),
        )
    if name == "create_prd":
        prd = prd_svc.create_prd(
            db, title=args["title"], template=args.get("template", "standard"),
            project_id=pid, body=args.get("body"),
        )
        return _prd_dict(prd)
    if name == "update_prd":
        prd = prd_svc.get_prd(db, args["prd_id"])
        if prd is None:
            raise errors.NotFound(f"prd not found: {args['prd_id']}")
        if prd.project_id not in allowed:
            raise authz.Forbidden(f"prd {args['prd_id']!r} is outside this key's project scope")
        updated = prd_svc.update_prd(
            db, args["prd_id"],
            title=args.get("title"), status=args.get("status"), body=args.get("body"),
        )
        return _prd_dict(updated)
    if name == "grill_prd":
        prd = prd_svc.get_prd(db, args["prd_id"])
        if prd is None:
            raise errors.NotFound(f"prd not found: {args['prd_id']}")
        if prd.project_id not in readable:
            raise authz.Forbidden(f"prd {args['prd_id']!r} is outside this key's project scope")
        return {"prd_id": prd.id, "questions": prd_svc.ai_command(db, prd.id, "grill")}
    if name == "describe_code":
        return code_svc.describe_code(
            db, project_id=pid,
            nodes=args.get("nodes", []),
            edges=args.get("edges", []),
            prune=bool(args.get("prune", False)),
        )
    if name == "get_code_map":
        return code_svc.get_code_map(db, pid, kind=args.get("kind"))
    if name == "code_neighbors":
        return code_svc.neighbors(db, pid, args["path"])
    if name == "search_code":
        top_k = args.get("top_k", 5)
        hits = code_svc.search_code(db, args["query"], project_id=pid, top_k=top_k)
        results = [{**code_svc.node_dict(n), "score": round(score, 4)} for n, score in hits]
        return {"results": results, "returned": len(results), "top_k": top_k}
    if name == "link_code":
        ref = code_svc.link_code(
            db, project_id=pid, ref_id=args["ref_id"], path=args["path"],
            relation=args.get("relation", "affects"), ref_type=args.get("ref_type"),
        )
        return code_svc.ref_dict(ref)
    if name == "unlink_code":
        removed = code_svc.unlink_code(
            db, project_id=pid, ref_id=args["ref_id"], path=args["path"], relation=args.get("relation"),
        )
        return {"removed": removed}
    if name == "report_agentledger_issue":
        try:
            result = up_svc.submit_upstream(
                type_=args.get("type", "feedback"), title=args["title"],
                detail=args.get("detail", ""), source="mcp-agent",
            )
        except httpx.HTTPError as e:
            raise errors.Conflict(f"upstream unreachable: {e}", hint="retry later")
        req = result.get("request", {})
        return {
            "ok": True, "request_id": req.get("id"),
            "target": up_svc.target_host(), "duplicates": result.get("duplicates", []),
        }
    raise errors.Validation(f"unknown tool: {name}", hint="call tools/list for the available tools")


def _audit_tool(db: Session, key: ApiKey, name: str, result: Any) -> None:
    """Best-effort audit of an accepted agent mutation. Pulls the target id and
    project from the tool result where present (most write tools echo them)."""
    target_id, project_id = "", None
    if isinstance(result, dict):
        target_id = str(result.get("id") or result.get("request_id") or "")
        project_id = result.get("project_id")
    events_svc.record_key(
        db, key, action=name,
        target_type="item" if name in _ITEM_WRITE_TOOLS else "",
        target_id=target_id, project_id=project_id,
    )


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


def _tool_error(id_: Any, code: str, message: str, hint: str | None = None) -> dict:
    """A tool-level failure. Reported via isError so the agent sees it, with a stable
    machine-readable `code` in structuredContent to branch on and an optional `hint`
    naming the corrective action (AL-47)."""
    err: dict[str, Any] = {"code": code, "message": message}
    if hint:
        err["hint"] = hint
    text = f"{code}: {message}" + (f" ({hint})" if hint else "")
    return _rpc_result(
        id_,
        {
            "content": [{"type": "text", "text": text}],
            "structuredContent": {"error": err},
            "isError": True,
        },
    )


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(get_agent_key),
):
    # Body parsing is inside the guard now — a malformed or non-object body is a
    # JSON-RPC parse error, not a raw HTTP 500 that escapes the envelope (AL-47).
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _rpc_error(None, -32700, "parse error: request body is not valid JSON")
    if not isinstance(body, dict):
        return _rpc_error(None, -32600, "invalid request: body must be a JSON object")
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
        try:
            # Validate arguments against the declared schema before dispatch, so a
            # bad call is an actionable error rather than a KeyError or a silently
            # accepted junk value (AL-47).
            _validate_args(name, args)
            # Run tool dispatch (sync DB + any outbound IO like report_agentledger_issue) off
            # the event loop, so a slow/hanging tool never blocks the async server — and a
            # same-host upstream loop-back can still be served concurrently.
            result = await run_in_threadpool(_call_tool, db, name, args, key)
        except authz.Forbidden as e:
            # Authenticated but out of scope: distinct code so agents can branch
            # (retry won't help — a different key or membership grant will).
            return _tool_error(id_, "unauthorized", str(e))
        except errors.AppError as e:
            # Expected, agent-correctable failure: not_found | validation | conflict.
            return _tool_error(id_, e.code, str(e), e.hint)
        except ValueError as e:
            # A service rejected the input (bad enum, unknown project, etc.).
            return _tool_error(id_, "validation", str(e))
        except KeyError as e:
            # A required arg slipped past validation (belt and braces).
            return _tool_error(id_, "validation", f"missing argument: {e}")
        except Exception:  # noqa: BLE001 — never leak a raw 500 to a JSON-RPC client
            logger.exception("MCP tool %r failed", name)
            db.rollback()
            return _tool_error(id_, "internal", f"internal error executing {name!r}",
                               hint="safe to retry once; if it persists, report it")
        # Meter only successful calls, after dispatch — failed/unknown-tool calls no
        # longer inflate the MCP Tools dashboard (AL-47).
        mcp_stats.increment(db, name)
        # Audit every accepted agent mutation, attributed to the key (AL-43).
        if name not in _READ_ONLY:
            _audit_tool(db, key, name, result)
        return _success(id_, result)

    return _rpc_error(id_, -32601, f"method not found: {method}")
