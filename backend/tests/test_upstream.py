"""Upstream 'Report an issue with AgentLedger' — forwards a user/agent report to the
maintainer's intake. httpx is mocked so nothing leaves the test process."""
import json as _json

import app.services.upstream as up_svc


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _fake_post(url, json=None, timeout=None):
    _fake_post.last = {"url": url, "json": json}
    return _FakeResp({"request": {"id": "R-42", "title": (json or {}).get("title")}, "duplicates": []})


def _mcp(client, key, name, args):
    r = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": name, "arguments": args}},
        headers={"X-API-Key": key},
    )
    return _json.loads(r.json()["result"]["content"][0]["text"])


def test_upstream_config_default_enabled(client, auth):
    r = client.get("/api/reports/upstream", headers=auth)
    assert r.status_code == 200
    d = r.json()
    assert d["enabled"] is True
    assert d["target"] == "feedback.asc-me.dev"  # from the default upstream URL


def test_upstream_config_requires_auth(client):
    assert client.get("/api/reports/upstream").status_code == 401


def test_upstream_report_forwards(client, auth, monkeypatch):
    monkeypatch.setattr(up_svc.httpx, "post", _fake_post)
    r = client.post(
        "/api/reports/upstream",
        json={"type": "bug", "title": "search_code 500s on empty query", "detail": "repro: …"},
        headers=auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["request_id"] == "R-42"
    # forwarded to the configured upstream project with the right shape
    sent = _fake_post.last["json"]
    assert sent["project_id"] == "agentledger"
    assert sent["type"] == "bug"
    assert sent["source_url"] == "agentledger:in-app"


def test_upstream_report_requires_auth(client):
    assert client.post("/api/reports/upstream", json={"title": "x"}).status_code == 401


def test_upstream_disabled_when_url_blank(client, auth, monkeypatch):
    monkeypatch.setattr(up_svc.settings, "upstream_feedback_url", "")
    assert client.get("/api/reports/upstream", headers=auth).json()["enabled"] is False
    r = client.post("/api/reports/upstream", json={"title": "x"}, headers=auth)
    assert r.status_code == 400  # not configured


def test_mcp_report_agentledger_issue(client, auth, monkeypatch):
    monkeypatch.setattr(up_svc.httpx, "post", _fake_post)
    key = client.post("/api/api-keys", json={"name": "reporter"}, headers=auth).json()["plaintext"]
    out = _mcp(client, key, "report_agentledger_issue",
               {"type": "feature", "title": "Add a dark-mode toggle", "detail": "…"})
    assert out["ok"] is True and out["request_id"] == "R-42"
    assert out["target"] == "feedback.asc-me.dev"
    assert _fake_post.last["json"]["source_url"] == "agentledger:mcp-agent"
