"""Provider-agnostic tool-calling layer (AL-172).

One internal contract that both provider families translate to/from, plus a driver
that runs the advertise → call → execute → feed-back loop. Adapters own their own
wire format (OpenAI function calling vs Anthropic native tools) behind a `ToolSession`;
the driver here is provider-neutral. Design + parity proof: the AL-180 spike
(docs/spikes/al-180-tool-calling-parity.md).

Tool-call *arguments* are always buffered — the two providers fragment streaming
tool-call arguments differently, so a session assembles them from fragments and decodes
once complete (the AL-180 parity choice). Assistant *text*, by contrast, can be streamed
token-level via the optional `stream_turn` (AL-183); `run_turn` remains the buffered
variant for non-SSE callers (run_tool_loop).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

MAX_ITERS = 8  # hard cap so a model that never stops calling tools can't loop forever


@dataclass(frozen=True)
class ToolSpec:
    """A tool advertised to the model. `input_schema` is JSON Schema."""
    name: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asked us to run. `input` is ALWAYS a decoded object — the
    OpenAI path decodes its JSON-string arguments at the boundary so callers never
    see provider-specific encoding (the parity gotcha from AL-180)."""
    id: str
    name: str
    input: dict


@dataclass(frozen=True)
class ToolResult:
    """The outcome of running a tool, fed back to the model. `is_error` lets the model
    self-correct once; it's native on Anthropic and folded into text on OpenAI."""
    id: str
    content: str
    is_error: bool = False


@dataclass
class ToolTurn:
    """One model turn, normalized across providers."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    wants_tools: bool = False  # provider's stop signal, normalized (tool_calls / tool_use)
    usage: dict | None = None  # {input, output} token counts when the provider reports them (AL-179)


@runtime_checkable
class ToolSession(Protocol):
    """A stateful conversation with one provider. The adapter owns message history in
    its own wire format; the driver only sees normalized turns."""

    def run_turn(self, tools: list[ToolSpec]) -> ToolTurn:
        """Send the conversation (advertising `tools`), append the assistant turn to
        history, and return it normalized."""
        ...

    def add_results(self, results: list[ToolResult]) -> None:
        """Append tool results to history in the provider's expected shape."""
        ...

    def stream_turn(self, tools: list[ToolSpec]):
        """Optional streaming variant of `run_turn` (AL-183): a GENERATOR that yields
        assistant text deltas (str) as they arrive and RETURNS the normalized `ToolTurn`
        via `StopIteration.value` (tool_calls + usage assembled from the buffered turn).
        Adapters that can't stream may omit this; SSE callers fall back to `run_turn`."""
        ...


def run_tool_loop(
    session: ToolSession,
    tools: list[ToolSpec],
    execute: Callable[[ToolCall], ToolResult],
    *,
    max_iters: int = MAX_ITERS,
) -> ToolTurn:
    """Drive the loop until the model stops requesting tools or the cap trips.

    `execute(call)` runs a tool and returns its result. (In the AL-177 propose-then-
    approve flow this instead stages a proposal and returns a "queued for approval"
    result — the loop shape is unchanged.) Returns the final turn; its `.text` is the
    assistant's closing message."""
    turn = session.run_turn(tools)
    iters = 1
    while turn.wants_tools and turn.tool_calls and iters < max_iters:
        session.add_results([execute(call) for call in turn.tool_calls])
        turn = session.run_turn(tools)
        iters += 1
    return turn
