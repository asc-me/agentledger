"""AL-175: assistant chat surface — threads, the SSE message loop, apply/reject, picker."""
import json

from app.providers.toolcall import ToolCall, ToolTurn


def _login(client, email="alex@ascme-labs.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


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


def _new_thread(client, auth, entity_type="item", entity_id="AL-08"):
    return client.post("/api/assistant/threads", json={
        "project_id": "core", "entity_type": entity_type, "entity_id": entity_id}, headers=auth).json()


# ---- threads ----
def test_create_list_get_thread(client, auth):
    t = _new_thread(client, auth, "prd", "PRD-1")
    assert t["entity_type"] == "prd" and t["provider"]  # defaults to project active provider

    listed = client.get("/api/assistant/threads?project_id=core&entity_type=prd&entity_id=PRD-1",
                        headers=auth).json()
    assert [x["id"] for x in listed] == [t["id"]]

    detail = client.get(f"/api/assistant/threads/{t['id']}", headers=auth).json()
    assert detail["id"] == t["id"] and detail["messages"] == []


def test_create_thread_rejects_bad_entity(client, auth):
    r = client.post("/api/assistant/threads",
                    json={"project_id": "core", "entity_type": "epic", "entity_id": "X"}, headers=auth)
    assert r.status_code == 422


def test_message_with_stub_streams_text_and_persists(client, auth):
    t = _new_thread(client, auth)  # defaults to the stub provider on core
    r = client.post(f"/api/assistant/threads/{t['id']}/message",
                    json={"message": "what is this item about?"}, headers=auth)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = _events(r.text)
    assert ("delta" in [e for e, _ in events]) and events[-1][0] == "done"
    # user + assistant messages persisted
    detail = client.get(f"/api/assistant/threads/{t['id']}", headers=auth).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


def test_message_stages_a_write_then_apply_executes_it(client, auth, monkeypatch):
    from app.routers import assistant as router

    class _FakeSession:
        def __init__(self):
            self.n = 0

        def run_turn(self, tools):
            self.n += 1
            if self.n == 1:  # first turn: request a write tool
                return ToolTurn(tool_calls=[ToolCall(id="c1", name="update_item",
                                                     input={"status": "review"})], wants_tools=True)
            return ToolTurn(text="I've proposed setting it to review.", wants_tools=False)

        def add_results(self, results):
            pass

    class _FakeChat:
        def tool_session(self, *, system, context, question):
            return _FakeSession()

    monkeypatch.setattr(router.platform_svc, "resolve_chat_for",
                        lambda db, pid, prov: ("openai", _FakeChat()))

    t = _new_thread(client, auth)  # item AL-08
    r = client.post(f"/api/assistant/threads/{t['id']}/message",
                    json={"message": "mark it in review"}, headers=auth)
    events = _events(r.text)
    kinds = [e for e, _ in events]
    assert "tool_call" in kinds and "proposed_action" in kinds and kinds[-1] == "done"

    # the write did NOT execute yet — it's staged
    assert client.get("/api/items/AL-08", headers=auth).json()["status"] != "review"
    action = json.loads(next(d for e, d in events if e == "proposed_action"))
    assert action["tool"] == "update_item" and action["status"] == "pending"

    # approve → executes
    applied = client.post(f"/api/assistant/actions/{action['id']}/apply", headers=auth).json()
    assert applied["status"] == "applied"
    assert client.get("/api/items/AL-08", headers=auth).json()["status"] == "review"


def test_reject_action_leaves_no_change(client, auth, monkeypatch):
    from app.routers import assistant as router

    class _S:
        def run_turn(self, tools):
            return ToolTurn(tool_calls=[ToolCall(id="c1", name="update_item", input={"status": "done"})],
                            wants_tools=True) if not getattr(self, "d", False) else ToolTurn(wants_tools=False)

        def add_results(self, results):
            self.d = True

    monkeypatch.setattr(router.platform_svc, "resolve_chat_for",
                        lambda db, pid, prov: ("openai", type("C", (), {"tool_session": lambda s, **k: _S()})()))
    t = _new_thread(client, auth)
    r = client.post(f"/api/assistant/threads/{t['id']}/message", json={"message": "close it"}, headers=auth)
    action = json.loads(next(d for e, d in _events(r.text) if e == "proposed_action"))
    assert client.post(f"/api/assistant/actions/{action['id']}/reject", headers=auth).json()["status"] == "rejected"
    assert client.get("/api/items/AL-08", headers=auth).json()["status"] != "done"


def test_read_only_user_cannot_apply(client, auth, monkeypatch):
    from app.routers import assistant as router

    class _S:
        def run_turn(self, tools):
            return ToolTurn(tool_calls=[ToolCall(id="c1", name="update_item", input={"status": "review"})],
                            wants_tools=True) if not getattr(self, "d", False) else ToolTurn(wants_tools=False)

        def add_results(self, results):
            self.d = True

    monkeypatch.setattr(router.platform_svc, "resolve_chat_for",
                        lambda db, pid, prov: ("openai", type("C", (), {"tool_session": lambda s, **k: _S()})()))
    t = _new_thread(client, auth)  # owner stages
    r = client.post(f"/api/assistant/threads/{t['id']}/message", json={"message": "review it"}, headers=auth)
    action = json.loads(next(d for e, d in _events(r.text) if e == "proposed_action"))
    ops = _login(client, "ops@ascme-labs.com")  # read-only on core
    assert client.post(f"/api/assistant/actions/{action['id']}/apply", headers=ops).status_code == 403


def test_ollama_thread_does_not_500(client, auth, monkeypatch):
    """AL-184: an Ollama-backed thread used to crash (OllamaChat had no tool_session).
    It now streams through Ollama's OpenAI-compatible endpoint."""
    from app.providers import openai_compat

    client.patch("/api/platform", json={"providers": {
        "ollama": {"base_url": "http://ollama.local:11434", "chat_model": "qwen2.5-coder"}}}, headers=auth)

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": {"content": "Hi from Ollama."}}]}

    monkeypatch.setattr(openai_compat.httpx, "post", lambda *a, **k: _R())

    t = client.post("/api/assistant/threads", json={
        "project_id": "core", "entity_type": "item", "entity_id": "AL-08", "provider": "ollama"},
        headers=auth).json()
    r = client.post(f"/api/assistant/threads/{t['id']}/message", json={"message": "hi"}, headers=auth)

    assert r.status_code == 200
    kinds = [e for e, _ in _events(r.text)]
    assert "delta" in kinds and kinds[-1] == "done"
    detail = client.get(f"/api/assistant/threads/{t['id']}", headers=auth).json()
    assert detail["messages"][-1]["content"] == "Hi from Ollama."


def test_providers_and_set_model(client, auth):
    client.patch("/api/platform", json={"active_chat_provider": "openai",
                 "providers": {"openai": {"api_key": "sk-x", "chat_model": "gpt-4o-mini"}}}, headers=auth)
    provs = client.get("/api/assistant/providers?project_id=core", headers=auth).json()["providers"]
    ids = {p["id"] for p in provs}
    assert "stub" not in ids and next(p for p in provs if p["id"] == "openai")["configured"] is True

    t = _new_thread(client, auth)
    updated = client.post(f"/api/assistant/threads/{t['id']}/model",
                          json={"provider": "openai", "model": "gpt-4o-mini"}, headers=auth).json()
    assert updated["provider"] == "openai" and updated["model"] == "gpt-4o-mini"
