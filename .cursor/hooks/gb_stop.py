#!/usr/bin/env python3
"""Cursor `stop` hook — nudge the agent to close the Graphban loop.

When the agent loop finishes successfully, remind it to move its claimed item to
review and capture lessons. `loop_limit` in hooks.json stops this from re-firing.

CAVEAT: `stop` / `afterAgentResponse` may not fire reliably in Cursor CLOUD agents as
of v3.11 — treat this as a best-effort nudge, not a guarantee. The durable driver of
the loop is the `sessionStart` primer + the sub-agent prompts, not this hook.

I/O: reads `{status, loop_count}` on stdin; writes `{}` or `{"followup_message": "..."}`.
"""
import json
import sys


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        print("{}")
        return
    if data.get("status") == "completed":
        print(json.dumps({
            "followup_message": (
                "If you completed a claimed item: update_item(status=\"review\") and run "
                "extract_lessons, then get_backlog for the next ready item."
            )
        }))
    else:
        print("{}")


if __name__ == "__main__":
    main()
