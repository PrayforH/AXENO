"""Claude SDK PreToolUse bridge to Harness policy and approvals."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
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
from harness.policy.profiles import PolicyProfileRegistry
from harness.policy.rules import PolicyEngine
from harness.runtime.audit_redaction import redact_text, redact_tool_arguments
from harness.runtime.base import RuntimeContext
from harness.runtime.input_redaction import (
    STAGED_INPUT_READ_MARKER,
    staged_input_paths,
    staged_read_path,
)


class ToolGate(Protocol):
    def hooks(
        self,
        context: RuntimeContext,
        *,
        policy_id: str | None = None,
        subagent_policy_ids: Mapping[str, str] | None = None,
    ) -> dict[HookEvent, list[HookMatcher]]: ...


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
def _approval_argument_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in _APPROVAL_ARGUMENT_KEYS:
        value = arguments.get(key)
        if isinstance(value, str):
            summary[key] = redact_text(value)
        elif isinstance(value, list):
            values = cast(list[object], value)
            if all(isinstance(item, str) for item in values):
                summary[key] = [
                    redact_text(item, limit=200)
                    for item in values[:5]
                    if isinstance(item, str)
                ]
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
        policy: PolicyEngine | None = None,
        profiles: PolicyProfileRegistry | None = None,
        approvals: ApprovalService,
        events: EventService,
    ) -> None:
        if (policy is None) == (profiles is None):
            raise ValueError("configure exactly one policy engine or profile registry")
        self._policy = policy
        self._profiles = profiles
        self._approvals = approvals
        self._events = events

    def hooks(
        self,
        context: RuntimeContext,
        *,
        policy_id: str | None = None,
        subagent_policy_ids: Mapping[str, str] | None = None,
    ) -> dict[HookEvent, list[HookMatcher]]:
        active_policy_id = policy_id or "local-standard"
        policy = (
            self._profiles.resolve(active_policy_id)
            if self._profiles is not None
            else self._policy
        )
        assert policy is not None
        subagent_policies: dict[str, tuple[str, PolicyEngine]] = {}
        if subagent_policy_ids:
            if self._profiles is None:
                subagent_policies = {
                    name: (active_policy_id, policy)
                    for name in subagent_policy_ids
                }
            else:
                subagent_policies = {
                    name: (child_policy_id, self._profiles.resolve(child_policy_id))
                    for name, child_policy_id in subagent_policy_ids.items()
                }
        implicit_deny = PolicyEngine([])

        async def pre_tool_use(
            hook_input: HookInput,
            _tool_use_id: str | None,
            _hook_context: HookContext,
        ) -> HookJSONOutput:
            typed_input = cast(PreToolUseHookInput, hook_input)
            selected_policy_id = active_policy_id
            selected_policy = policy
            if subagent_policies:
                agent_type = str(typed_input.get("agent_type") or "")
                agent_id = str(typed_input.get("agent_id") or "")
                key = (
                    agent_type
                    if agent_type in subagent_policies
                    else agent_id if agent_id in subagent_policies else ""
                )
                if key:
                    selected_policy_id, selected_policy = subagent_policies[key]
                elif agent_type or agent_id:
                    selected_policy_id = "unknown-subagent"
                    selected_policy = implicit_deny
            return await self._authorize(
                context,
                typed_input,
                policy=selected_policy,
                policy_id=selected_policy_id,
            )

        return {
            "PreToolUse": [
                HookMatcher(matcher=None, hooks=[pre_tool_use], timeout=900.0)
            ]
        }

    async def _authorize(
        self,
        context: RuntimeContext,
        hook_input: PreToolUseHookInput,
        *,
        policy: PolicyEngine,
        policy_id: str,
    ) -> SyncHookJSONOutput:
        tool_name = hook_input["tool_name"]
        tool_call_id = hook_input["tool_use_id"]
        arguments = hook_input["tool_input"]
        request_payload: dict[str, Any] = {
            "name": tool_name,
            "tool_call_id": tool_call_id,
            "arguments": arguments,
            "policy_checked": True,
            "policy_profile": policy_id,
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
        audit_arguments = request_payload.get("arguments")
        if isinstance(audit_arguments, dict):
            request_payload["arguments"] = redact_tool_arguments(
                tool_name, cast(dict[str, Any], audit_arguments)
            )
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
        result = policy.evaluate(
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
            try:
                decision = await self._approvals.wait_for_decision(
                    approval.approval_id
                )
            except asyncio.CancelledError:
                await asyncio.shield(
                    self._approvals.cancel_pending(
                        tenant_id=context.run.tenant_id,
                        approval_id=approval.approval_id,
                        reason="tool authorization wait interrupted",
                    )
                )
                raise
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
