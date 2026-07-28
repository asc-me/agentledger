#!/usr/bin/env python3
"""Cursor `afterFileEdit` hook — best-effort claim-lease warning.

`afterFileEdit` fires AFTER the edit and cannot block (Cursor exposes no
`beforeFileEdit`), so this WARNS rather than prevents: if an edited file falls outside
the claimed item's touchpoints, it surfaces a message so the agent double-checks it
isn't colliding with another worker. Silent (fail-open) when nothing is claimed.

The claim manifest is read from AGENTLEDGER_CLAIM_FILE
(default `.cursor/agentledger-claim.json`) — see `.cursor/agentledger-claim.example.json`.
A fuller version would query the live claim over MCP and block pre-edit once Cursor
exposes a blocking file hook; that's a follow-up.

I/O: reads `{file_path, workspace_roots, ...}` on stdin; writes `{}` (silent) or
`{"user_message": "..."}` on stdout.
"""
import fnmatch
import json
import os
import sys
from pathlib import Path


def rel_to_workspace(file_path, roots):
    p = Path(file_path)
    for root in roots or []:
        try:
            return p.resolve().relative_to(Path(root).resolve()).as_posix()
        except Exception:
            continue
    return p.name


def matches(rel, touchpoint):
    """Match AgentLedger-style: exact, glob, or directory prefix."""
    tp = (touchpoint or "").strip()
    if not tp:
        return False
    if fnmatch.fnmatch(rel, tp):
        return True
    base = tp.rstrip("/")
    if rel == base or rel.startswith(base + "/"):
        return True
    return fnmatch.fnmatch(rel, base + "/*")


def load_manifest():
    path = os.environ.get("AGENTLEDGER_CLAIM_FILE", ".cursor/agentledger-claim.json")
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        print("{}")
        return
    manifest = load_manifest()
    touchpoints = (manifest or {}).get("touchpoints") or []
    if not manifest or not touchpoints:
        print("{}")  # nothing claimed / no touchpoints declared — fail open
        return
    rel = rel_to_workspace(data.get("file_path", ""), data.get("workspace_roots"))
    if any(matches(rel, tp) for tp in touchpoints):
        print("{}")
        return
    item = manifest.get("item_id", "the claimed item")
    print(json.dumps({
        "user_message": (
            f"AgentLedger: edited {rel}, which is outside {item}'s touchpoints "
            f"({', '.join(touchpoints)}). Confirm you're not colliding with another "
            f"agent's work — or update the item's touchpoints if this is intended."
        )
    }))


if __name__ == "__main__":
    main()
