"""Claude SDK PreToolUse bridge to Harness policy and approvals."""

from __future__ import annotations

import re
from typing import Any, Protocol, cast

from claude_agent_sdk import HookMatcher
from claude_agent_sdk.types import (
    HookContext,
    HookEvent,
    HookInput,
    HookJSONOutput,
    PreToolUseHookInput,
    SyncHookJSONOutput,
)

from harness.application.approvals import ApprovalService
from harness.application.events import EventService
from harness.core.models import ApprovalStatus
from harness.policy.models import PolicyContext, PolicyDecision
from harness.policy.rules import PolicyEngine
from harness.runtime.base import RuntimeContext
from harness.runtime.input_redaction import (
    STAGED_INPUT_READ_MARKER,
    staged_input_paths,
    staged_read_path,
)


class ToolGate(Protocol):
    def hooks(self, context: RuntimeContext) -> dict[HookEvent, list[HookMatcher]]: ...


_APPROVAL_ARGUMENT_KEYS = (
    "command",
    "file_path",
    "path",
    "query",
    "url",
    "urls",
    "description",
    "subagent_type",
    "pattern",
    "glob",
)
_AUTHORIZATION_TEXT = re.compile(
    r"(?i)\b(authorization\s*[:=]\s*)([^'\"\n]+)"
)
_BEARER_TEXT = re.compile(r"(?i)\b(bearer\s+)([^\s'\"&]+)")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(token|api[_-]?key|secret|password)(\s*[:=]\s*)([^\s'\"&]+)"
)


def _safe_text(value: str, *, limit: int = 500) -> str:
    redacted = _AUTHORIZATION_TEXT.sub(r"\1[REDACTED]", value)
    redacted = _BEARER_TEXT.sub(r"\1[REDACTED]", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", redacted)
    return redacted if len(redacted) <= limit else f"{redacted[: limit - 1]}…"


def _approval_argument_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in _APPROVAL_ARGUMENT_KEYS:
        value = arguments.get(key)
        if isinstance(value, str):
            summary[key] = _safe_text(value)
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            summary[key] = [_safe_text(item, limit=200) for item in value[:5]]
    return summary


def _approval_risk(tool_name: str) -> str:
    if tool_name == "Bash":
        return "high"
    if tool_name in {"Write", "Edit"}:
        return "medium"
    return "low"


def _hook_output(decision: str, reason: str) -> SyncHookJSONOutput:
    return cast(
        SyncHookJSONOutput,
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        },
    )


class SdkToolGate:
    """Build a catch-all SDK hook that decides before tool execution."""

    def __init__(
        self,
        *,
        policy: PolicyEngine,
        approvals: ApprovalService,
        events: EventService,
    ) -> None:
        self._policy = policy
        self._approvals = approvals
        self._events = events

    def hooks(self, context: RuntimeContext) -> dict[HookEvent, list[HookMatcher]]:
        async def pre_tool_use(
            hook_input: HookInput,
            _tool_use_id: str | None,
            _hook_context: HookContext,
        ) -> HookJSONOutput:
            typed_input = cast(PreToolUseHookInput, hook_input)
            return await self._authorize(context, typed_input)

        return {
            "PreToolUse": [
                HookMatcher(matcher=None, hooks=[pre_tool_use], timeout=900.0)
            ]
        }

    async def _authorize(
        self,
        context: RuntimeContext,
        hook_input: PreToolUseHookInput,
    ) -> SyncHookJSONOutput:
        tool_name = hook_input["tool_name"]
        tool_call_id = hook_input["tool_use_id"]
        arguments = hook_input["tool_input"]
        request_payload: dict[str, Any] = {
            "name": tool_name,
            "tool_call_id": tool_call_id,
            "arguments": arguments,
            "policy_checked": True,
            "message_id": context.assistant_message_id,
            "sandbox": {
                "provider": context.sandbox_provider,
                "isolation": context.sandbox_isolation.value,
            },
        }
        relative_input_path = staged_read_path(
            request_payload,
            workspace=context.workspace,
            staged_paths=staged_input_paths(context.workspace, context.input_files),
        )
        if relative_input_path is not None:
            safe_arguments = dict(arguments)
            safe_arguments["file_path"] = relative_input_path
            request_payload["arguments"] = safe_arguments
            request_payload[STAGED_INPUT_READ_MARKER] = True
        agent_id = hook_input.get("agent_id")
        if agent_id:
            request_payload["agent_id"] = agent_id
        await self._events.append(
            tenant_id=context.run.tenant_id,
            run_id=context.run.run_id,
            session_id=context.run.session_id,
            event_type="tool.request",
            payload=request_payload,
        )
        result = self._policy.evaluate(
            PolicyContext(
                tenant_id=context.run.tenant_id,
                agent_name=context.session.agent_name,
                tool_name=tool_name,
                arguments=arguments,
                sandbox_isolation=context.sandbox_isolation,
            )
        )

        if result.decision is PolicyDecision.DENY:
            await self._append_denied(context, tool_call_id, result.reason)
            return _hook_output("deny", result.reason)

        if result.decision is PolicyDecision.ASK:
            approval = await self._approvals.request(
                tenant_id=context.run.tenant_id,
                run_id=context.run.run_id,
                tool_call_id=tool_call_id,
                reason=result.reason,
                message_id=context.assistant_message_id,
                inline=True,
                tool_name=tool_name,
                argument_summary=_approval_argument_summary(arguments),
                sandbox_provider=context.sandbox_provider,
                sandbox_isolation=context.sandbox_isolation.value,
                policy_rule=result.rule_name,
                risk=_approval_risk(tool_name),
            )
            decision = await self._approvals.wait_for_decision(approval.approval_id)
            if decision is not ApprovalStatus.APPROVED:
                return _hook_output("deny", "tool use was not approved")

        await self._events.append(
            tenant_id=context.run.tenant_id,
            run_id=context.run.run_id,
            session_id=context.run.session_id,
            event_type="tool.allowed",
            payload={"tool_call_id": tool_call_id},
        )
        return _hook_output("allow", result.reason)

    async def _append_denied(
        self,
        context: RuntimeContext,
        tool_call_id: str,
        reason: str,
    ) -> None:
        await self._events.append(
            tenant_id=context.run.tenant_id,
            run_id=context.run.run_id,
            session_id=context.run.session_id,
            event_type="tool.result",
            payload={
                "tool_call_id": tool_call_id,
                "is_error": True,
                "error": {"code": "policy_denied", "message": reason},
            },
        )
