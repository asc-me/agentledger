"""Local MCP proxy for the local-first hybrid (AL-138).

When a local instance is LINKED to a cloud tenant, agents talk to the LOCAL `/api/mcp`, but
only the code-graph tools run locally — the graph is built and authoritative here. Everything
else (items, claims, memory, PRDs, backlog…) is forwarded to the cloud, which stays
authoritative for mutable, contended state (D2). Unlinked, nothing is forwarded — a pure
local tool.

The local endpoint authenticates the incoming LOCAL key as usual; a proxied call is made with
the org-minted link credential (`SYNC_API_KEY`), so the CLOUD applies its own authz, metering,
and audit — the local side never double-counts.
"""
from __future__ import annotations

import httpx

from app.config import settings

_TIMEOUT = 30.0

# Served LOCALLY even when linked: the code graph (built + authoritative here), the code↔item
# bridge (graph-adjacent), key introspection, and the separate upstream issue reporter.
LOCAL_TOOLS = {
    "describe_code", "get_code_map", "code_neighbors", "search_code",
    "link_code", "unlink_code", "get_context",
    # MUST stay local (AL-284). Proxying happens BEFORE dispatch, so a linked instance
    # would forward this to the cloud and create the project in the org's tenant space —
    # exactly the authority action the gate refuses. Kept local, the refusal fires.
    "create_project",
    # Both names, because the proxy decides local-vs-remote BEFORE the dispatcher
    # normalizes aliases — a retired name must not start proxying to the cloud (AL-262).
    "report_graphban_issue", "report_agentledger_issue",
}


def enabled() -> bool:
    """True when this instance is linked to a cloud tenant (so non-graph tools proxy)."""
    return bool(settings.sync_cloud_url and settings.sync_api_key)


def should_proxy(name: str) -> bool:
    return enabled() and name not in LOCAL_TOOLS


def forward(name: str, args: dict) -> dict:
    """Forward a `tools/call` to the cloud tenant's MCP endpoint; return the raw JSON-RPC
    response (`{result}` or `{error}`)."""
    url = settings.sync_cloud_url.rstrip("/")
    resp = httpx.post(
        f"{url}/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": name, "arguments": args}},
        headers={"X-API-Key": settings.sync_api_key},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()
