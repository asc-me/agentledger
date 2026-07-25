"""Action safety & audit for the in-app assistant (AL-177) — propose-then-approve.

A write tool call the assistant makes does NOT execute. It's staged as a pending
`AssistantProposedAction`; the human `apply`s (which runs the underlying op, captures the
prior value for reversibility, and records an audit event attributed to
`assistant:<provider>`) or `reject`s. Because writes require explicit approval,
prompt-injected content in an item/PRD/memory can at most *propose* a rejected action —
it can never cause an unapproved write.

`executor()` is the `execute` the AL-172 tool loop calls: reads run immediately, writes
stage. AL-175 wires it into the SSE loop; the apply/reject endpoints call this too.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import AssistantProposedAction, AssistantThread, Item, Prd, utcnow
from app.providers.toolcall import ToolCall, ToolResult
from app.security import authz
from app.services import assistant_tools as at
from app.services import events as events_svc

_REVERTIBLE = {"update_item", "update_prd"}  # tools whose prior_value can be re-applied


def _ctx(db: Session, thread: AssistantThread, user_id: str) -> at.ToolContext:
    return at.ToolContext(db=db, user_id=user_id, project_id=thread.project_id,
                          entity_type=thread.entity_type, entity_id=thread.entity_id)


def process_call(
    db: Session, thread: AssistantThread, user_id: str, call: ToolCall
) -> tuple[ToolResult, AssistantProposedAction | None]:
    """Route one tool call for the assistant loop: reads execute immediately; writes stage
    a pending proposal. Returns (result-fed-back-to-model, proposed action or None). The
    SSE surface uses the returned action to emit a `proposed_action` event."""
    ctx = _ctx(db, thread, user_id)
    kind = at.tool_kind(call.name)
    if kind is None:
        return ToolResult(id=call.id, content=f"unknown tool: {call.name}", is_error=True), None
    if kind == "read":
        return at.dispatch(ctx, call), None  # dispatch enforces read authz
    # write → stage behind approval
    if not at.is_available(ctx, call.name):
        return ToolResult(id=call.id, is_error=True,
                          content=f"{call.name} is not available on a {ctx.entity_type} thread"), None
    if not authz.can_write(db, user_id, thread.project_id):
        return ToolResult(id=call.id, content="not authorized to write in this project", is_error=True), None
    action = stage(db, thread, call)
    return ToolResult(id=call.id, content=f"Proposed (awaiting your approval): {action.summary}"), action


def executor(db: Session, thread: AssistantThread, user_id: str):
    """The `execute` callback for run_tool_loop (non-streaming callers): reads execute,
    writes stage. SSE callers use process_call directly to surface proposals."""
    def execute(call: ToolCall) -> ToolResult:
        return process_call(db, thread, user_id, call)[0]

    return execute


def stage(db: Session, thread: AssistantThread, call: ToolCall) -> AssistantProposedAction:
    """Record a write as a pending proposed action. Does not execute or authz-check — the
    caller (executor) gates; apply() re-checks authz at execution time."""
    action = AssistantProposedAction(
        id="pa_" + uuid.uuid4().hex[:12],
        thread_id=thread.id,
        project_id=thread.project_id,
        tool=call.name,
        args=call.input or {},
        summary=_summarize(thread, call),
        status="pending",
        provider=thread.provider,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def list_pending(db: Session, thread_id: str) -> list[AssistantProposedAction]:
    return [a for a in _thread_actions(db, thread_id) if a.status == "pending"]


def apply(db: Session, action_id: str, *, user_id: str) -> tuple[AssistantProposedAction | None, str]:
    """Execute a pending proposal: authz-re-checked, prior value captured, audited. Returns
    (action, result_text). Non-pending or unauthorized → an error string, no state change."""
    action = db.get(AssistantProposedAction, action_id)
    if action is None:
        return None, "proposed action not found"
    if action.status != "pending":
        return action, f"already {action.status}"
    thread = db.get(AssistantThread, action.thread_id)
    ctx = _ctx(db, thread, user_id)

    prior = _capture_prior(db, ctx, action)  # snapshot BEFORE the change, for revert
    result = at.dispatch(ctx, ToolCall(id=action.id, name=action.tool, input=action.args))
    if result.is_error:
        return action, result.content  # leave pending so it can be retried/rejected

    action.prior_value = prior
    action.status = "applied"
    action.decided_at = utcnow()
    events_svc.record(
        db, actor_type="user", actor_id=user_id, surface="rest",
        action="assistant_apply", target_type=thread.entity_type, target_id=thread.entity_id,
        project_id=thread.project_id,
        meta={"origin": f"assistant:{action.provider}", "tool": action.tool,
              "args": action.args, "prior": prior},
    )
    db.commit()
    return action, result.content


def reject(db: Session, action_id: str) -> AssistantProposedAction | None:
    action = db.get(AssistantProposedAction, action_id)
    if action is None or action.status != "pending":
        return action
    action.status = "rejected"
    action.decided_at = utcnow()
    db.commit()
    return action


def revert(db: Session, action_id: str, *, user_id: str) -> tuple[AssistantProposedAction | None, str]:
    """Undo an applied write by re-applying its captured prior value (update_* only)."""
    action = db.get(AssistantProposedAction, action_id)
    if action is None:
        return None, "proposed action not found"
    if action.status != "applied":
        return action, f"cannot revert a {action.status} action"
    if action.tool not in _REVERTIBLE or not action.prior_value:
        return action, f"{action.tool} is not revertible"
    thread = db.get(AssistantThread, action.thread_id)
    ctx = _ctx(db, thread, user_id)
    result = at.dispatch(ctx, ToolCall(id=action.id, name=action.tool, input=action.prior_value))
    if result.is_error:
        return action, result.content
    action.status = "reverted"
    action.decided_at = utcnow()
    events_svc.record(
        db, actor_type="user", actor_id=user_id, surface="rest", action="assistant_revert",
        target_type=thread.entity_type, target_id=thread.entity_id, project_id=thread.project_id,
        meta={"tool": action.tool, "restored": action.prior_value},
    )
    db.commit()
    return action, result.content


# ---- helpers ----
def _thread_actions(db: Session, thread_id: str) -> list[AssistantProposedAction]:
    from sqlalchemy import select

    return list(db.scalars(
        select(AssistantProposedAction)
        .where(AssistantProposedAction.thread_id == thread_id)
        .order_by(AssistantProposedAction.created_at.asc())
    ).all())


def _capture_prior(db: Session, ctx: at.ToolContext, action: AssistantProposedAction) -> dict | None:
    """Snapshot the fields the write will change, so the action is reversible."""
    if action.tool == "update_item":
        item = db.get(Item, ctx.entity_id)
        if item:
            return {k: getattr(item, k) for k in action.args if k in ("status", "description", "effort")}
    elif action.tool == "update_prd":
        prd = db.get(Prd, ctx.entity_id)
        if prd:
            return {k: getattr(prd, k) for k in action.args if k in ("body", "status")}
    return None


def _summarize(thread: AssistantThread, call: ToolCall) -> str:
    args = call.input or {}
    if call.name == "update_item":
        changes = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"Update {thread.entity_id}: {changes}"
    if call.name == "update_prd":
        return f"Update PRD {thread.entity_id}: {', '.join(args)}"
    if call.name == "create_item":
        return f"Create item: {args.get('title', '')!r}"
    if call.name == "add_memory":
        text = str(args.get("text", ""))
        return f"Propose memory: {text[:60]}"
    return f"{call.name}({args})"
