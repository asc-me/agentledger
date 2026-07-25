"""SPIKE (AL-180) — prototype, not production. Proves that ONE internal tool-calling
contract translates cleanly to/from both provider families:

  - Anthropic (Claude)      — native Messages tool use
  - OpenAI-compatible        — OpenAI / xAI Grok / Groq / DeepSeek / … function calling
    (this is the path Grok and ChatGPT both take through app.providers.openai_compat)

The point of the spike is to de-risk AL-172 (the real provider tool-calling layer) by
finding where the two wire formats disagree BEFORE the contract is locked. Findings are
written up in docs/spikes/al-180-tool-calling-parity.md. This module is deliberately
pure/translation-only (no network, no SDK) so the parity can be unit-tested hermetically.

Verified against current provider docs (2026-07): Anthropic Messages tool use and the
OpenAI-compatible /chat/completions function-calling shape.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


# ---- The internal, provider-agnostic contract (PRD-9 §Provider tool-calling layer) ----
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict  # JSON Schema


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict  # ALWAYS a decoded object — never a JSON string (see PARITY NOTE 2)


@dataclass
class ToolResult:
    id: str
    content: str
    is_error: bool = False


@dataclass
class Turn:
    """One model turn's output in provider-agnostic form."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    wants_tools: bool = False  # provider said "I stopped to call tools" (see PARITY NOTE 4)


# =============================== OpenAI-compatible ===============================
# Grok + ChatGPT both take this path. Tool spec nests under {"type":"function", ...};
# the model's arguments come back as a JSON *string* under function.arguments.

def to_openai_tools(specs: list[ToolSpec]) -> list[dict]:
    return [
        {"type": "function",
         "function": {"name": s.name, "description": s.description, "parameters": s.input_schema}}
        for s in specs
    ]


def parse_openai_choice(choice: dict) -> Turn:
    """Translate one `choices[0]` from a /chat/completions response into a Turn."""
    msg = choice.get("message", {})
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        # PARITY NOTE 2: arguments is a JSON string here — decode to an object so the
        # internal ToolCall.input matches Anthropic's already-decoded object.
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), input=args))
    return Turn(
        text=msg.get("content") or "",
        tool_calls=calls,
        wants_tools=choice.get("finish_reason") == "tool_calls",
    )


def openai_followup_messages(assistant_msg: dict, results: list[ToolResult]) -> list[dict]:
    """The messages to append before the next call: the assistant turn (verbatim, so the
    tool_calls it made are preserved) followed by one `role:"tool"` message per result."""
    out = [assistant_msg]
    for r in results:
        # PARITY NOTE 3a: results are their own `role:"tool"` messages keyed by tool_call_id.
        # OpenAI has no per-result error flag — an error is just text content.
        out.append({"role": "tool", "tool_call_id": r.id, "content": r.content})
    return out


# ================================== Anthropic ===================================
# Flat tool spec with input_schema; tool calls arrive as `tool_use` content blocks
# whose `input` is already a decoded object.

def to_anthropic_tools(specs: list[ToolSpec]) -> list[dict]:
    return [{"name": s.name, "description": s.description, "input_schema": s.input_schema} for s in specs]


def parse_anthropic_message(message: dict) -> Turn:
    """Translate a Messages API response (content blocks + stop_reason) into a Turn."""
    text_parts, calls = [], []
    for block in message.get("content") or []:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            calls.append(ToolCall(id=block.get("id", ""), name=block.get("name", ""),
                                  input=block.get("input") or {}))
    return Turn(
        text="".join(text_parts),
        tool_calls=calls,
        wants_tools=message.get("stop_reason") == "tool_use",  # PARITY NOTE 4
    )


def anthropic_followup_messages(assistant_content: list[dict], results: list[ToolResult]) -> list[dict]:
    """Append the assistant turn (its content blocks verbatim) then a SINGLE user message
    carrying all tool_result blocks (PARITY NOTE 3b: results are grouped into one user
    message, not one message each — the opposite grouping from OpenAI)."""
    return [
        {"role": "assistant", "content": assistant_content},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r.id, "content": r.content, "is_error": r.is_error}
            for r in results
        ]},
    ]


# ============================ Provider-agnostic driver ===========================
def run_tool_loop(turn_fn, tools: list[ToolSpec], execute, *, max_iters: int = 8) -> Turn:
    """Drive the advertise → call → execute → feed-back loop against ANY provider.

    `turn_fn(tools) -> Turn` runs one model turn (the caller closes over provider +
    message history and appends the follow-up messages the translators return).
    `execute(ToolCall) -> ToolResult` runs a tool (in AL-172 this stages a proposal
    for human approval instead — the loop shape is identical). Terminates when the model
    stops requesting tools or the iteration cap trips (PARITY NOTE 5: same termination
    rule both providers, keyed on the normalized `wants_tools`)."""
    last = Turn()
    for _ in range(max_iters):
        last = turn_fn(tools)
        if not last.wants_tools or not last.tool_calls:
            return last
        for call in last.tool_calls:
            execute(call)  # result is threaded back inside turn_fn's closure in real use
    return last
