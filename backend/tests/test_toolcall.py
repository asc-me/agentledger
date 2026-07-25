"""Provider tool-calling layer (AL-172) — hermetic round trips for both real adapters.

openai_compat is exercised by mocking `httpx.post`; anthropic by mocking the SDK client.
Both are driven through the SAME `run_tool_loop` + `execute`, proving one contract drives
both provider families end to end (the AL-180 parity finding, now in production code).
"""
import types

from app.providers import anthropic_provider, openai_compat
from app.providers.toolcall import ToolResult, ToolSpec, run_tool_loop

_SPEC = ToolSpec(
    name="update_item",
    description="Advance an item's status.",
    input_schema={"type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string"}}},
)


def _execute_capture():
    seen = []

    def execute(call):
        seen.append((call.name, call.input))
        return ToolResult(id=call.id, content="ok")

    return execute, seen


# ---------------------------- OpenAI-compatible (Grok/ChatGPT) ----------------------------
class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_openai_compat_tool_round_trip(monkeypatch):
    responses = [
        {"choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "update_item",
                                         "arguments": '{"id": "AL-9", "status": "done"}'}}]}}]},
        {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "Done — AL-9 is marked done."}}]},
    ]
    sent_bodies = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent_bodies.append(json)
        return _FakeResp(responses[len(sent_bodies) - 1])

    monkeypatch.setattr(openai_compat.httpx, "post", fake_post)

    chat = openai_compat.chat("https://api.example/v1", "sk-x", "grok-2-latest")
    session = chat.tool_session(system="sys", context="ctx", question="mark AL-9 done")
    execute, seen = _execute_capture()
    final = run_tool_loop(session, [_SPEC], execute)

    # tool ran once with the DECODED object (not the JSON string)
    assert seen == [("update_item", {"id": "AL-9", "status": "done"})]
    # first request advertised the tool in OpenAI function shape
    assert sent_bodies[0]["tools"][0]["function"]["name"] == "update_item"
    # the result was fed back as a role:"tool" message keyed by tool_call_id
    tool_msg = next(m for m in sent_bodies[1]["messages"] if m.get("role") == "tool")
    assert tool_msg == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}
    # loop terminated on the final text turn
    assert final.text == "Done — AL-9 is marked done." and not final.wants_tools


def test_openai_compat_error_result_is_flagged_in_text(monkeypatch):
    responses = [
        {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
            {"id": "call_1", "function": {"name": "update_item", "arguments": "{}"}}]}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]},
    ]
    sent = []
    monkeypatch.setattr(openai_compat.httpx, "post",
                        lambda *a, json=None, **k: (sent.append(json) or _FakeResp(responses[len(sent) - 1])))
    session = openai_compat.chat("https://x/v1", "k", "m").tool_session(system="s", context="c", question="q")
    run_tool_loop(session, [_SPEC], lambda call: ToolResult(id=call.id, content="not writable", is_error=True))
    tool_msg = next(m for m in sent[1]["messages"] if m.get("role") == "tool")
    assert tool_msg["content"] == "ERROR: not writable"  # no is_error flag on OpenAI → in text


# --------------------------------- Anthropic (Claude) ---------------------------------
def _block(**kw):
    return types.SimpleNamespace(**kw)


class _FakeMessages:
    def __init__(self, outbound):
        self._outbound = outbound
        self.calls = []

    def create(self, **kwargs):
        # Snapshot messages at call time — the session mutates its list in place, and the
        # real SDK serializes on send, so we capture membership as it was for this call.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._outbound[len(self.calls) - 1]


def test_anthropic_tool_round_trip(monkeypatch):
    outbound = [
        types.SimpleNamespace(stop_reason="tool_use", content=[
            _block(type="text", text="Marking it done."),
            _block(type="tool_use", id="toolu_1", name="update_item",
                   input={"id": "AL-9", "status": "done"})]),
        types.SimpleNamespace(stop_reason="end_turn", content=[
            _block(type="text", text="Done — AL-9 is marked done.")]),
    ]
    fake_client = types.SimpleNamespace(messages=_FakeMessages(outbound))
    monkeypatch.setattr(anthropic_provider, "_client", lambda api_key="": fake_client)

    chat = anthropic_provider.chat("sk-ant", "claude-opus-4-8")
    session = chat.tool_session(system="sys", context="ctx", question="mark AL-9 done")
    execute, seen = _execute_capture()
    final = run_tool_loop(session, [_SPEC], execute)

    assert seen == [("update_item", {"id": "AL-9", "status": "done"})]
    # tool advertised in Anthropic flat shape
    assert fake_client.messages.calls[0]["tools"][0]["input_schema"] == _SPEC.input_schema
    # results fed back as ONE user message of tool_result blocks
    followup = fake_client.messages.calls[1]["messages"][-1]
    assert followup["role"] == "user"
    assert followup["content"][0] == {"type": "tool_result", "tool_use_id": "toolu_1",
                                      "content": "ok", "is_error": False}
    assert final.text == "Done — AL-9 is marked done." and not final.wants_tools


# --------------------------------- Stub degradation ---------------------------------
def test_stub_tool_session_terminates_without_tools():
    from app.providers.stub import StubChat

    session = StubChat().tool_session(system="s", context="grounding facts", question="q")
    calls = []
    final = run_tool_loop(session, [_SPEC], lambda c: calls.append(c) or ToolResult(id=c.id, content="x"))
    assert calls == []  # stub never requests tools
    assert "grounding facts" in final.text and not final.wants_tools


def test_loop_respects_iteration_cap():
    from app.providers.toolcall import ToolCall, ToolTurn

    class _Runaway:
        def run_turn(self, tools):
            return ToolTurn(tool_calls=[ToolCall(id="x", name="update_item", input={})], wants_tools=True)

        def add_results(self, results):
            pass

    n = {"c": 0}
    run_tool_loop(_Runaway(), [_SPEC], lambda c: (n.__setitem__("c", n["c"] + 1), ToolResult(id="x", content="ok"))[1],
                  max_iters=3)
    assert n["c"] == 2  # capped: max_iters bounds model turns, so execute runs max_iters-1 times
