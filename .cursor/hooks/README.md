# AgentLedger Cursor hooks (AL-214 / PRD-11 §D3)

`.cursor/hooks.json` wires Cursor's agent lifecycle to the AgentLedger loop — MCP
exposes the tools, hooks supply the *when*. All handlers are stdlib Python (no `jq`),
read the event JSON on stdin, and write a JSON decision on stdout.

| Hook | Handler | Effect |
| --- | --- | --- |
| `sessionStart`  | `al_session_start.py`  | Injects the operating-loop primer as `additional_context` (+ a live `get_context` snapshot when `AGENTLEDGER_MCP_URL`/`AGENTLEDGER_API_KEY` are set). |
| `afterFileEdit` | `al_after_file_edit.py`| **Warns** when an edited file is outside the claimed item's touchpoints. |
| `stop`          | `al_stop.py`           | Best-effort `followup_message` nudging `update_item(review)` + `extract_lessons`. |

## Honest limits (why these hooks and not others)

- **`afterFileEdit` can't block.** It fires *after* the edit and Cursor exposes no
  `beforeFileEdit`, so lease enforcement here is a **warning**, not prevention. A
  blocking version needs either a future pre-edit hook or gating writes at
  `beforeMCPExecution`.
- **`stop` is unreliable in cloud.** As of v3.11 `stop`/`afterAgentResponse` may not
  fire in cloud agents. The durable loop driver is the `sessionStart` primer plus the
  sub-agent prompts in [`../agents/`](../agents/README.md) — the `stop` hook is a bonus.
- **Context injection lives at `sessionStart`, not `beforeSubmitPrompt`.**
  `beforeSubmitPrompt` can only allow/block; only `sessionStart` returns
  `additional_context`.

## The claim manifest

`al_after_file_edit.py` reads the current claim from `AGENTLEDGER_CLAIM_FILE`
(default `.cursor/agentledger-claim.json`, git-ignored). Shape — see
[`../agentledger-claim.example.json`](../agentledger-claim.example.json):

```json
{ "item_id": "AL-123", "agent_id": "al-implementer", "touchpoints": ["backend/app/services/*"] }
```

No manifest, or no `touchpoints`, ⇒ the hook stays silent (fail-open). Writing this
file when an agent claims an item is the loop's job (a follow-up can have `claim_next`
emit it, or read the live claim over MCP).

## Environment

| Var | Used by | Purpose |
| --- | --- | --- |
| `AGENTLEDGER_MCP_URL` + `AGENTLEDGER_API_KEY` | `al_session_start.py` | Optional live `get_context` enrichment (fail-open). |
| `AGENTLEDGER_CLAIM_FILE` | `al_after_file_edit.py` | Override the claim-manifest path. |

Handlers are covered by `backend/tests/test_cursor_hooks.py` (config validity, wiring,
and each handler's decision), so CI's backend job catches drift.
