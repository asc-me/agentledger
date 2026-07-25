# AL-180 spike — tool-calling parity (Anthropic vs OpenAI-compatible)

**Goal:** prove that a single internal tool-calling contract can drive both provider
families before AL-172 locks the design. **Verdict: proven.** One `{ToolSpec, ToolCall,
ToolResult}` contract + one driver loop translate cleanly to/from both. The differences
are all at the *edges* (spec shape, argument encoding, result grouping, stop signal,
streaming) and each is a mechanical translation, not a semantic mismatch.

Prototype: `backend/app/providers/_spike_toolcall.py` · proof: `backend/tests/test_spike_toolcall.py`
(5 tests, hermetic — raw wire payloads from current docs, no network/SDK).

> Scope: **Claude = `anthropic` (native tools)**, **Grok + ChatGPT = `openai_compat`
> (OpenAI function calling)** — Grok (`xai`) and ChatGPT (`openai`) share one adapter, so
> v1 is really two integrations, not three. Shapes verified against the current Anthropic
> Messages and OpenAI-compatible `/chat/completions` docs (2026-07).

## Parity table

| Concern | OpenAI-compatible (Grok/ChatGPT) | Anthropic (Claude) | Translation |
|---|---|---|---|
| **Tool spec** | `{"type":"function","function":{name,description,parameters}}` | `{name,description,input_schema}` (flat) | Same JSON Schema inside; wrap vs flatten. |
| **Tool call** | `message.tool_calls[].{id, function:{name, arguments}}` | content block `{type:"tool_use", id, name, input}` | **`arguments` is a JSON *string*; `input` is an object.** Normalize with `json.loads` so `ToolCall.input` is always a decoded dict. |
| **Stop signal** | `finish_reason == "tool_calls"` | `stop_reason == "tool_use"` | Normalize to `Turn.wants_tools`. |
| **Result feedback** | one `{"role":"tool", tool_call_id, content}` **per result** | one **user** message whose content is all `tool_result` blocks (keyed by `tool_use_id`) | Opposite grouping (N messages vs 1 message of N blocks). Both key by the provider's call id. |
| **Error result** | no flag — error is just text content | `tool_result.is_error: true` | Carry `is_error` internally; drop it (fold into text) on the OpenAI path. |
| **Parallel calls** | array of `tool_calls` in one assistant message | multiple `tool_use` blocks in one message | Both supported; loop handles a list either way. |
| **Assistant echo** | append the assistant message verbatim (must keep `tool_calls`) | append the assistant `content` blocks verbatim (must keep `tool_use`) | Same rule: echo the turn before the results. |

## The one real gotcha: streaming tool calls

Both providers **fragment the tool arguments across streaming deltas** and both must be
accumulated by index — but the event shapes differ:

- **OpenAI:** `choices[].delta.tool_calls[]` with an `index` and partial `function.arguments`
  string fragments to concatenate.
- **Anthropic:** `content_block_start` (type `tool_use`) → `content_block_delta` with
  `input_json_delta` (partial JSON) → `content_block_stop`; `message_delta` carries the
  final `stop_reason`.

**Recommendation for AL-172:** in v1, run **tool-call turns non-streaming** (buffer the full
turn, then translate) and stream only the *final* assistant text turn to the UI. That gives
identical parity with far less code, and the assistant chat surface (AL-175) already streams
plain text the same way. Revisit incremental tool-call streaming only if the "thinking…"
latency on a tool turn proves unacceptable — it's an optimization, not a correctness need.

## What this locks for AL-172

- The PRD-9 contract (`{name, description, input_schema}` / `{id, name, input}` /
  `{id, content, is_error}`) is correct as written — keep it.
- Build the **`openai_compat` path first** (covers Grok *and* ChatGPT); the `anthropic`
  path is a second, smaller translator over the same contract.
- **`ToolCall.input` must be a decoded object** at the boundary — decode OpenAI's
  `arguments` string immediately so the assistant tool surface never sees provider-specific
  encoding. (This is the single most likely source of a subtle bug.)
- Loop termination keys on the normalized `wants_tools` with a hard `max_iters` cap
  (default 8) — same rule both providers.
- The prototype is translation-only; the real adapters extend
  `app/providers/openai_compat.py` (httpx: add `tools` to the request body, parse
  `tool_calls`) and `app/providers/anthropic_provider.py` (SDK: `tools=` param, read
  `tool_use` blocks, feed back `tool_result` blocks).

## Deliberately out of the spike
Live end-to-end calls (the instance runs the stub provider; no keys) — the proof is at the
translation layer, which is where parity actually lives. Incremental tool-call *streaming*
is deferred per the recommendation above.
