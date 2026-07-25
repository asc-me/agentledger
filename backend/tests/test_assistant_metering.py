"""AL-179: cost & quota metering — per-conversation tokens, quota gate, graceful degradation."""
import json

from app.providers.toolcall import ToolTurn


def _events(text: str):
    out = []
    for block in text.strip().split("\n\n"):
        ev = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        if ev:
            out.append((ev, data))
    return out


def _thread(client, auth):
    return client.post("/api/assistant/threads",
                       json={"project_id": "core", "entity_type": "item", "entity_id": "AL-08"},
                       headers=auth).json()


class _UsageChat:
    """A provider that answers in one text turn and reports token usage."""
    def tool_session(self, *, system, context, question):
        class _S:
            def run_turn(self, tools):
                return ToolTurn(text="Here's my take.", wants_tools=False,
                                usage={"input": 120, "output": 30})
            def add_results(self, results):
                pass
        return _S()


def test_token_usage_metered_on_thread_and_streamed(client, auth, monkeypatch):
    from app.routers import assistant as router
    monkeypatch.setattr(router.platform_svc, "resolve_chat_for",
                        lambda db, pid, prov: ("openai", _UsageChat()))
    t = _thread(client, auth)
    r = client.post(f"/api/assistant/threads/{t['id']}/message", json={"message": "hi"}, headers=auth)

    usage = json.loads(next(d for e, d in _events(r.text) if e == "usage"))
    assert usage["input"] == 120 and usage["output"] == 30
    # accumulated on the thread and visible on the detail
    detail = client.get(f"/api/assistant/threads/{t['id']}", headers=auth).json()
    assert detail["input_tokens"] == 120 and detail["output_tokens"] == 30

    # a second turn accumulates
    client.post(f"/api/assistant/threads/{t['id']}/message", json={"message": "more"}, headers=auth)
    detail2 = client.get(f"/api/assistant/threads/{t['id']}", headers=auth).json()
    assert detail2["input_tokens"] == 240 and detail2["output_tokens"] == 60


def test_quota_exceeded_degrades_with_a_clear_message(client, auth, monkeypatch):
    from app.errors import QuotaExceeded
    from app.routers import assistant as router
    monkeypatch.setattr(router.platform_svc, "resolve_chat_for",
                        lambda db, pid, prov: ("openai", _UsageChat()))

    def _boom(db, org_id):
        raise QuotaExceeded("monthly call limit reached (10000) on the free plan",
                            hint="ask an operator to upgrade the plan")
    monkeypatch.setattr(router.quotas, "meter_call", _boom)

    t = _thread(client, auth)
    r = client.post(f"/api/assistant/threads/{t['id']}/message", json={"message": "hi"}, headers=auth)
    kinds = [e for e, _ in _events(r.text)]
    assert "error" in kinds and "delta" not in kinds  # explained, model never ran
    err = json.loads(next(d for e, d in _events(r.text) if e == "error"))
    assert "call limit reached" in err["message"]


def test_stub_provider_emits_a_graceful_notice(client, auth):
    t = _thread(client, auth)  # defaults to the offline stub on core
    r = client.post(f"/api/assistant/threads/{t['id']}/message", json={"message": "hi"}, headers=auth)
    kinds = [e for e, _ in _events(r.text)]
    assert "notice" in kinds and kinds[-1] == "done"
