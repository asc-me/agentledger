"""OpenAI-compatible chat adapter — one adapter for every provider that speaks the
OpenAI `/chat/completions` shape (OpenAI, Groq, DeepSeek, Mistral, xAI, Gemini's compat
endpoint). Parameterized by base_url + api_key + model; plain httpx, no SDK dependency.
"""
from __future__ import annotations

import json

import httpx

from app.config import settings
from app.providers.toolcall import ToolCall, ToolResult, ToolSpec, ToolTurn


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(settings.llm_timeout_seconds, connect=5.0)


def _messages(system: str, context: str, question: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Project context:\n{context}\n\nQuestion: {question}"},
    ]


class OpenAICompatChat:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def chat(self, *, system: str, context: str, question: str) -> str:
        """Full completion as a string — assembled from the STREAM, not a blocking POST.

        A non-streaming completion returns nothing until the whole generation finishes,
        so time-to-first-byte equals total generation time. Behind an edge proxy that
        caps TTFB (~100s on Cloudflare) a long answer — the PRD rewrite in
        `grill_apply` is the worst case — gets severed mid-thought. Streaming makes the
        first byte immediate, so only the *total* duration matters, while callers keep
        the identical `-> str` contract."""
        return "".join(self.stream(system=system, context=context, question=question)).strip()

    def stream(self, *, system: str, context: str, question: str):
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={"model": self.model, "messages": _messages(system, context, question), "stream": True},
            timeout=_timeout(),
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta

    def _complete(self, messages: list[dict], tools: list[ToolSpec]) -> dict:
        """Non-streaming completion advertising `tools` — the tool-call turn (AL-172).
        Buffered on purpose: OpenAI streams tool-call arguments as partial fragments,
        so parity with Anthropic is simpler off the stream."""
        body: dict = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
                for t in tools
            ]
        r = httpx.post(f"{self.base_url}/chat/completions", headers=self._headers(),
                       json=body, timeout=_timeout())
        r.raise_for_status()
        return r.json()

    def tool_session(self, *, system: str, context: str, question: str) -> "OpenAICompatToolSession":
        return OpenAICompatToolSession(self, system, context, question)


class OpenAICompatToolSession:
    """Owns the OpenAI-format message history for one tool-calling conversation."""

    def __init__(self, chat: OpenAICompatChat, system: str, context: str, question: str):
        self._chat = chat
        self.messages: list[dict] = _messages(system, context, question)

    def run_turn(self, tools: list[ToolSpec]) -> ToolTurn:
        resp = self._chat._complete(self.messages, tools)
        choice = resp["choices"][0]
        msg = choice.get("message", {})
        self.messages.append(msg)  # echo the assistant turn verbatim (keeps its tool_calls)
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:  # arguments is a JSON *string* — decode at the boundary
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), input=args))
        u = resp.get("usage") or {}
        return ToolTurn(text=msg.get("content") or "", tool_calls=calls,
                        wants_tools=choice.get("finish_reason") == "tool_calls",
                        usage={"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)}
                        if u else None)

    def add_results(self, results: list[ToolResult]) -> None:
        for r in results:
            # OpenAI: one role:"tool" message per result. No error flag — mark it in text.
            content = f"ERROR: {r.content}" if r.is_error else r.content
            self.messages.append({"role": "tool", "tool_call_id": r.id, "content": content})


class OpenAICompatExtractor:
    def __init__(self, base_url: str, api_key: str, model: str):
        self._chat = OpenAICompatChat(base_url, api_key, model)

    def extract(self, *, title: str, description: str) -> list[str]:
        system = (
            "You distill a completed dev task into 1-3 durable, reusable memory shards "
            "(decisions, learnings, conventions). Reply with one shard per line, no numbering."
        )
        out = self._chat.chat(system=system, context="", question=f"Task: {title}\n\nDetails: {description}")
        return [ln.strip("-• ").strip() for ln in out.splitlines() if ln.strip()][:3]


def chat(base_url: str, api_key: str, model: str) -> OpenAICompatChat:
    return OpenAICompatChat(base_url, api_key, model)


def extractor(base_url: str, api_key: str, model: str) -> OpenAICompatExtractor:
    return OpenAICompatExtractor(base_url, api_key, model)
