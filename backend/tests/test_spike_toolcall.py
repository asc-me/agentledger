"""SPIKE (AL-180) — parity proof for the tool-calling layer.

Feeds realistic RAW provider payloads (the exact wire shapes from the current Anthropic
and OpenAI-compatible docs) through the prototype translators and asserts both normalize
to the SAME internal ToolCall, and that one provider-agnostic driver completes an
identical two-turn round trip for each. No network, no SDK — pure translation.
"""
from app.providers._spike_toolcall import (
    ToolResult,
    ToolSpec,
    anthropic_followup_messages,
    openai_followup_messages,
    parse_anthropic_message,
    parse_openai_choice,
    run_tool_loop,
    to_anthropic_tools,
    to_openai_tools,
)

_SPEC = ToolSpec(
    name="update_item",
    description="Advance an item's status.",
    input_schema={"type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string"}},
                  "required": ["id", "status"]},
)

# --- raw wire payloads (verified against current provider docs) ---
_OPENAI_TOOLCALL_RESPONSE = {  # a /chat/completions choice that requests a tool
    "finish_reason": "tool_calls",
    "message": {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_abc",
            "type": "function",
            # NB: arguments is a JSON *string*
            "function": {"name": "update_item", "arguments": '{"id": "AL-9", "status": "done"}'},
        }],
    },
}
_ANTHROPIC_TOOLCALL_RESPONSE = {  # a Messages response that requests the same tool
    "stop_reason": "tool_use",
    "content": [
        {"type": "text", "text": "Marking it done."},
        # NB: input is already a decoded object
        {"type": "tool_use", "id": "toolu_abc", "name": "update_item", "input": {"id": "AL-9", "status": "done"}},
    ],
}


def test_tool_spec_translates_to_each_provider_shape():
    (oai,) = to_openai_tools([_SPEC])
    assert oai == {"type": "function", "function": {
        "name": "update_item", "description": "Advance an item's status.",
        "parameters": _SPEC.input_schema}}
    (ant,) = to_anthropic_tools([_SPEC])
    assert ant == {"name": "update_item", "description": "Advance an item's status.",
                   "input_schema": _SPEC.input_schema}


def test_both_providers_normalize_to_the_same_tool_call():
    oai = parse_openai_choice(_OPENAI_TOOLCALL_RESPONSE)
    ant = parse_anthropic_message(_ANTHROPIC_TOOLCALL_RESPONSE)

    assert oai.wants_tools and ant.wants_tools  # finish_reason vs stop_reason, normalized
    for turn in (oai, ant):
        assert len(turn.tool_calls) == 1
        call = turn.tool_calls[0]
        assert call.name == "update_item"
        # The decisive parity assertion: the JSON-string args and the object input land
        # on the SAME decoded object.
        assert call.input == {"id": "AL-9", "status": "done"}
    # provider-specific ids are preserved (needed to key the result back)
    assert oai.tool_calls[0].id == "call_abc"
    assert ant.tool_calls[0].id == "toolu_abc"


def test_result_feedback_shapes_diverge_as_documented():
    result = ToolResult(id="call_abc", content="ok", is_error=False)
    oai_msgs = openai_followup_messages(_OPENAI_TOOLCALL_RESPONSE["message"], [result])
    # OpenAI: assistant turn + a separate role:"tool" message keyed by tool_call_id
    assert oai_msgs[1] == {"role": "tool", "tool_call_id": "call_abc", "content": "ok"}

    ant_result = ToolResult(id="toolu_abc", content="ok")
    ant_msgs = anthropic_followup_messages(_ANTHROPIC_TOOLCALL_RESPONSE["content"], [ant_result])
    # Anthropic: assistant turn + ONE user message whose content is tool_result block(s)
    assert ant_msgs[1]["role"] == "user"
    assert ant_msgs[1]["content"][0] == {
        "type": "tool_result", "tool_use_id": "toolu_abc", "content": "ok", "is_error": False}


def _fake_provider(first_response_turn_parser, first_raw, final_text):
    """Build a turn_fn that returns a tool-call turn once, then a final text turn — using
    the given provider's real parser for the first turn."""
    state = {"calls": 0}

    def turn_fn(_tools):
        state["calls"] += 1
        if state["calls"] == 1:
            return first_response_turn_parser(first_raw)
        # second turn: model is done (no tools requested)
        from app.providers._spike_toolcall import Turn
        return Turn(text=final_text, wants_tools=False)

    return turn_fn


def test_one_driver_completes_the_loop_for_both_providers():
    executed = []

    def execute(call):
        executed.append((call.name, call.input))
        return ToolResult(id=call.id, content="done")

    oai_final = run_tool_loop(
        _fake_provider(parse_openai_choice, _OPENAI_TOOLCALL_RESPONSE, "OpenAI-compat: item updated."),
        [_SPEC], execute)
    ant_final = run_tool_loop(
        _fake_provider(parse_anthropic_message, _ANTHROPIC_TOOLCALL_RESPONSE, "Anthropic: item updated."),
        [_SPEC], execute)

    # Same driver, same execute(): both providers ran the tool once with identical input,
    # then terminated on a plain text turn.
    assert executed == [("update_item", {"id": "AL-9", "status": "done"}),
                        ("update_item", {"id": "AL-9", "status": "done"})]
    assert oai_final.text == "OpenAI-compat: item updated." and not oai_final.wants_tools
    assert ant_final.text == "Anthropic: item updated." and not ant_final.wants_tools


def test_driver_respects_the_iteration_cap():
    # A model that never stops asking for tools must be bounded, not loop forever.
    from app.providers._spike_toolcall import Turn, ToolCall
    def always_tools(_tools):
        return Turn(tool_calls=[ToolCall(id="x", name="update_item", input={})], wants_tools=True)
    calls = {"n": 0}
    def execute(_c):
        calls["n"] += 1
        return ToolResult(id="x", content="ok")
    run_tool_loop(always_tools, [_SPEC], execute, max_iters=3)
    assert calls["n"] == 3  # capped, not infinite
