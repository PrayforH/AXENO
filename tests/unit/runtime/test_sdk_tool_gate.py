import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from claude_agent_sdk import PreToolUseHookInput
from claude_agent_sdk.types import PostToolUseHookInput, SyncHookJSONOutput

from harness.adapters.memory import (
    InMemoryApprovalRepository,
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryRunRepository,
)
from harness.application.approvals import ApprovalService
from harness.application.events import EventService
from harness.core.errors import ConflictError
from harness.core.models import ApprovalStatus, Run, RunStatus, Session
from harness.policy.profiles import default_policy_profiles
from harness.policy.rules import PolicyEngine, default_policy_rules
from harness.quota.models import QuotaResource, ReplaceQuotaPolicyRequest
from harness.quota.repositories import InMemoryQuotaRepository
from harness.quota.service import QuotaService
from harness.runtime.base import RuntimeContext
from harness.runtime.sdk_tool_gate import SdkToolGate
from harness.sandbox.base import SandboxIsolation

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _ids() -> Callable[[str], str]:
    count = 0

    def generate(prefix: str) -> str:
        nonlocal count
        count += 1
        return f"{prefix}-{count}"

    return generate


async def _arrange(
    tmp_path: Path,
    *,
    sandbox_isolation: SandboxIsolation = SandboxIsolation.WORKSPACE,
    use_profiles: bool = False,
    quotas: QuotaService | None = None,
):
    runs = InMemoryRunRepository()
    approvals = InMemoryApprovalRepository()
    event_repository = InMemoryEventRepository()
    events = EventService(
        event_repository,
        InMemoryEventBus(),
        clock=lambda: NOW,
        id_generator=_ids(),
    )
    run = Run(
        run_id="run-sdk",
        session_id="session-sdk",
        tenant_id="tenant-a",
        status=RunStatus.RUNNING,
        idempotency_key="sdk-gate",
        created_at=NOW,
        updated_at=NOW,
    )
    await runs.add(run)
    approval_service = ApprovalService(
        runs=runs,
        approvals=approvals,
        events=events,
        clock=lambda: NOW,
        id_generator=_ids(),
        ttl=timedelta(minutes=5),
    )
    gate = (
        SdkToolGate(
            profiles=default_policy_profiles(),
            approvals=approval_service,
            events=events,
            quotas=quotas,
        )
        if use_profiles
        else SdkToolGate(
            policy=PolicyEngine(default_policy_rules()),
            approvals=approval_service,
            events=events,
            quotas=quotas,
        )
    )
    context = RuntimeContext(
        run=run,
        session=Session(
            session_id="session-sdk",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="domain-agent",
            agent_version="0.1.0",
            created_at=NOW,
        ),
        workspace=tmp_path,
        assistant_message_id="assistant-sdk-message",
        sandbox_provider=(
            "daytona" if sandbox_isolation is SandboxIsolation.CONTAINER else "local"
        ),
        sandbox_isolation=sandbox_isolation,
    )
    return gate, approval_service, runs, event_repository, context


def _input(
    name: str,
    arguments: dict[str, object],
    tool_use_id: str,
    *,
    agent_type: str = "",
):
    return cast(
        PreToolUseHookInput,
        {
            "session_id": "sdk-session",
            "transcript_path": "/tmp/transcript",
            "cwd": "/tmp/workspace",
            "hook_event_name": "PreToolUse",
            "tool_name": name,
            "tool_input": arguments,
            "tool_use_id": tool_use_id,
            "agent_id": "",
            "agent_type": agent_type,
        },
    )


async def _invoke(
    gate: SdkToolGate,
    context: RuntimeContext,
    hook_input: PreToolUseHookInput,
    *,
    policy_id: str | None = None,
) -> SyncHookJSONOutput:
    matcher = gate.hooks(context, policy_id=policy_id)["PreToolUse"][0]
    output = await matcher.hooks[0](
        hook_input,
        hook_input["tool_use_id"],
        {"signal": None},
    )
    return cast(SyncHookJSONOutput, output)


def _decision(output: SyncHookJSONOutput) -> str:
    specific = cast(dict[str, object], output.get("hookSpecificOutput", {}))
    return str(specific.get("permissionDecision", ""))


@pytest.mark.asyncio
async def test_manifest_policy_profile_controls_the_sdk_gate(tmp_path: Path) -> None:
    gate, _, _, events, context = await _arrange(tmp_path, use_profiles=True)

    output = await _invoke(
        gate,
        context,
        _input("Write", {"file_path": "result.txt"}, "tool-profile"),
        policy_id="production-read-only",
    )

    assert _decision(output) == "deny"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert emitted[-1].payload["error"]["code"] == "policy_denied"


@pytest.mark.asyncio
async def test_subagent_uses_its_own_policy_profile(tmp_path: Path) -> None:
    gate, _, _, events, context = await _arrange(tmp_path, use_profiles=True)
    matcher = gate.hooks(
        context,
        policy_id="production-orchestrator",
        subagent_policy_ids={"helper-agent": "production-read-only"},
    )["PreToolUse"][0]

    output = await matcher.hooks[0](
        _input(
            "Write",
            {"file_path": "result.txt"},
            "tool-subagent",
            agent_type="helper-agent",
        ),
        "tool-subagent",
        {"signal": None},
    )

    assert _decision(cast(SyncHookJSONOutput, output)) == "deny"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert emitted[0].payload["policy_profile"] == "production-read-only"
    assert not any(event.type == "approval.requested" for event in emitted)


@pytest.mark.asyncio
async def test_unknown_subagent_identity_fails_closed(tmp_path: Path) -> None:
    gate, _, _, events, context = await _arrange(tmp_path, use_profiles=True)
    matcher = gate.hooks(
        context,
        policy_id="production-orchestrator",
        subagent_policy_ids={"helper-agent": "production-read-only"},
    )["PreToolUse"][0]

    output = await matcher.hooks[0](
        _input(
            "Read",
            {"file_path": "evidence.txt"},
            "tool-unknown-subagent",
            agent_type="unregistered-agent",
        ),
        "tool-unknown-subagent",
        {"signal": None},
    )

    assert _decision(cast(SyncHookJSONOutput, output)) == "deny"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert emitted[0].payload["policy_profile"] == "unknown-subagent"


@pytest.mark.asyncio
async def test_allows_read_before_tool_execution_and_emits_ordered_events(tmp_path: Path) -> None:
    gate, _, _, events, context = await _arrange(tmp_path)

    output = await _invoke(gate, context, _input("Read", {"file_path": "a.txt"}, "tool-1"))

    assert _decision(output) == "allow"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert [event.type for event in emitted] == ["tool.request", "tool.allowed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resource", "tool_name"),
    [
        (QuotaResource.MCP_REQUESTS, "mcp__tavily__tavily_search"),
        (QuotaResource.CONCURRENT_SUBAGENTS, "Task"),
    ],
)
async def test_tool_gate_enforces_mcp_and_subagent_quota(
    tmp_path: Path,
    resource: QuotaResource,
    tool_name: str,
) -> None:
    quotas = QuotaService(InMemoryQuotaRepository())
    await quotas.replace_policy(
        tenant_id="tenant-a",
        user_id="owner-a",
        policy_id="tenant-default",
        request=ReplaceQuotaPolicyRequest(
            expectedRevision=0,
            limits={resource: 1},
        ),
    )
    gate, _, _, events, context = await _arrange(tmp_path, quotas=quotas)

    first = await _invoke(gate, context, _input(tool_name, {}, "quota-tool-1"))
    second = await _invoke(gate, context, _input(tool_name, {}, "quota-tool-2"))

    assert _decision(first) == "allow"
    assert _decision(second) == "deny"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert emitted[-1].payload["error"]["message"] == (
        f"quota exceeded for {resource.value}"
    )


@pytest.mark.asyncio
async def test_completed_subagent_releases_concurrency_for_next_delegation(
    tmp_path: Path,
) -> None:
    quotas = QuotaService(InMemoryQuotaRepository())
    await quotas.replace_policy(
        tenant_id="tenant-a",
        user_id="owner-a",
        policy_id="tenant-default",
        request=ReplaceQuotaPolicyRequest(
            expectedRevision=0,
            limits={QuotaResource.CONCURRENT_SUBAGENTS: 1},
        ),
    )
    gate, _, _, _, context = await _arrange(tmp_path, quotas=quotas)
    assert _decision(
        await _invoke(gate, context, _input("Task", {}, "delegation-one"))
    ) == "allow"
    post_input = cast(
        PostToolUseHookInput,
        {
            "session_id": "sdk-session",
            "transcript_path": "/tmp/transcript",
            "cwd": str(tmp_path),
            "hook_event_name": "PostToolUse",
            "tool_name": "Task",
            "tool_input": {},
            "tool_response": {"status": "completed"},
            "tool_use_id": "delegation-one",
        },
    )
    release_hook = gate.hooks(context)["PostToolUse"][1].hooks[0]
    await release_hook(post_input, "delegation-one", {"signal": None})

    assert _decision(
        await _invoke(gate, context, _input("Task", {}, "delegation-two"))
    ) == "allow"


@pytest.mark.asyncio
async def test_staged_input_read_persists_only_safe_path_and_marker(tmp_path: Path) -> None:
    gate, _, _, events, context = await _arrange(tmp_path)
    relative_path = "inputs/facts.txt"
    staged = tmp_path / relative_path
    staged.parent.mkdir()
    staged.write_text("private fact")
    context = context.model_copy(update={"input_files": (relative_path,)})

    output = await _invoke(
        gate,
        context,
        _input("Read", {"file_path": str(staged)}, "tool-input-read"),
    )

    assert _decision(output) == "allow"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    request = emitted[0]
    assert request.payload["arguments"] == {"file_path": relative_path}
    assert request.payload["staged_input_read"] is True
    assert str(tmp_path) not in repr(emitted)


@pytest.mark.asyncio
async def test_denies_destructive_bash_before_tool_execution(tmp_path: Path) -> None:
    gate, _, _, events, context = await _arrange(tmp_path)

    output = await _invoke(gate, context, _input("Bash", {"command": "rm -rf cache"}, "tool-2"))

    assert _decision(output) == "deny"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert [event.type for event in emitted] == ["tool.request", "tool.result"]
    assert emitted[-1].payload["error"]["code"] == "policy_denied"


@pytest.mark.asyncio
async def test_ask_waits_inline_and_continues_only_after_approval(tmp_path: Path) -> None:
    gate, approvals, runs, events, context = await _arrange(tmp_path)
    task = asyncio.create_task(_invoke(gate, context, _input("Bash", {"command": "ls"}, "tool-3")))
    requested = []
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    for _ in range(20):
        emitted = await events.list_after("tenant-a", "run-sdk", 0)
        requested = [event for event in emitted if event.type == "approval.requested"]
        if requested:
            break
        await asyncio.sleep(0)
    assert requested
    approval_id = str(requested[0].payload["approval_id"])
    assert not task.done()

    await approvals.decide(
        tenant_id="tenant-a",
        approval_id=approval_id,
        decision=ApprovalStatus.APPROVED,
    )
    output = await task

    assert _decision(output) == "allow"
    assert (await runs.get("tenant-a", "run-sdk")).status is RunStatus.RUNNING
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert emitted[-1].type == "tool.allowed"


@pytest.mark.asyncio
async def test_container_write_uses_trusted_context_without_approval(
    tmp_path: Path,
) -> None:
    gate, _, _, events, context = await _arrange(
        tmp_path,
        sandbox_isolation=SandboxIsolation.CONTAINER,
    )

    output = await asyncio.wait_for(
        _invoke(
            gate,
            context,
            _input(
                "Write",
                {
                    "file_path": "result.txt",
                    "content": "done",
                    "sandbox_isolation": "workspace",
                },
                "tool-container-write",
            ),
        ),
        timeout=0.1,
    )

    assert _decision(output) == "allow"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert [event.type for event in emitted] == ["tool.request", "tool.allowed"]
    assert emitted[0].payload["sandbox"] == {
        "provider": "daytona",
        "isolation": "container",
    }
    assert emitted[0].payload["message_id"] == "assistant-sdk-message"
    assert not any(event.type == "approval.requested" for event in emitted)


@pytest.mark.asyncio
async def test_local_write_waits_for_approval(tmp_path: Path) -> None:
    gate, approvals, _, events, context = await _arrange(tmp_path)
    task = asyncio.create_task(
        _invoke(
            gate,
            context,
            _input(
                "Write",
                {"file_path": "result.txt", "content": "done"},
                "tool-local-write",
            ),
        )
    )
    requested = []
    for _ in range(20):
        emitted = await events.list_after("tenant-a", "run-sdk", 0)
        requested = [event for event in emitted if event.type == "approval.requested"]
        if requested:
            break
        await asyncio.sleep(0)
    assert requested
    assert requested[0].payload["message_id"] == "assistant-sdk-message"
    assert requested[0].payload["tool_name"] == "Write"
    assert requested[0].payload["argument_summary"] == {"file_path": "result.txt"}
    assert requested[0].payload["sandbox_provider"] == "local"
    assert requested[0].payload["sandbox_isolation"] == "workspace"
    assert requested[0].payload["policy_rule"] == "write-review"
    assert requested[0].payload["risk"] == "medium"
    assert "done" not in repr(requested[0].payload)
    approval_id = str(requested[0].payload["approval_id"])

    await approvals.decide(
        tenant_id="tenant-a",
        approval_id=approval_id,
        decision=ApprovalStatus.APPROVED,
    )

    assert _decision(await task) == "allow"


@pytest.mark.asyncio
async def test_successful_approved_write_grants_same_run_edit_capability(
    tmp_path: Path,
) -> None:
    gate, approvals, _, events, context = await _arrange(tmp_path)
    hooks = gate.hooks(context)
    pre_tool_use = hooks["PreToolUse"][0].hooks[0]
    report = tmp_path / "outputs" / "report.md"
    write_input = _input(
        "Write",
        {"file_path": str(report), "content": "draft"},
        "tool-create-report",
    )
    write_task = asyncio.ensure_future(
        pre_tool_use(write_input, write_input["tool_use_id"], {"signal": None})
    )
    requested = []
    for _ in range(20):
        emitted = await events.list_after("tenant-a", "run-sdk", 0)
        requested = [event for event in emitted if event.type == "approval.requested"]
        if requested:
            break
        await asyncio.sleep(0)
    assert requested
    await approvals.decide(
        tenant_id="tenant-a",
        approval_id=str(requested[0].payload["approval_id"]),
        decision=ApprovalStatus.APPROVED,
    )
    assert _decision(cast(SyncHookJSONOutput, await write_task)) == "allow"

    post_input = cast(
        PostToolUseHookInput,
        {
            "session_id": "sdk-session",
            "transcript_path": "/tmp/transcript",
            "cwd": str(tmp_path),
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": write_input["tool_input"],
            "tool_response": {"ok": True},
            "tool_use_id": "tool-create-report",
        },
    )
    await hooks["PostToolUse"][0].hooks[0](post_input, "tool-create-report", {"signal": None})

    edit_input = _input(
        "Edit",
        {
            "file_path": "/workspace/outputs/report.md",
            "old_string": "draft",
            "new_string": "final",
        },
        "tool-edit-report",
    )
    edit_output = await asyncio.wait_for(
        pre_tool_use(edit_input, edit_input["tool_use_id"], {"signal": None}),
        timeout=0.1,
    )

    assert _decision(cast(SyncHookJSONOutput, edit_output)) == "allow"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert [event.type for event in emitted].count("approval.requested") == 1
    assert emitted[-1].type == "tool.allowed"


@pytest.mark.asyncio
async def test_write_tools_deny_paths_outside_the_run_workspace(tmp_path: Path) -> None:
    gate, _, _, events, context = await _arrange(tmp_path)

    output = await _invoke(
        gate,
        context,
        _input(
            "Edit",
            {
                "file_path": str(tmp_path.parent / "outside.md"),
                "old_string": "a",
                "new_string": "b",
            },
            "tool-edit-outside",
        ),
    )

    assert _decision(output) == "deny"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert [event.type for event in emitted] == ["tool.request", "tool.result"]
    assert emitted[-1].payload["error"]["code"] == "policy_denied"


@pytest.mark.asyncio
async def test_inline_rejection_denies_sdk_tool_without_terminal_run_event(
    tmp_path: Path,
) -> None:
    gate, approvals, runs, events, context = await _arrange(tmp_path)
    task = asyncio.create_task(
        _invoke(gate, context, _input("Bash", {"command": "pwd"}, "tool-rejected"))
    )
    requested = []
    for _ in range(20):
        emitted = await events.list_after("tenant-a", "run-sdk", 0)
        requested = [event for event in emitted if event.type == "approval.requested"]
        if requested:
            break
        await asyncio.sleep(0)
    assert requested

    await approvals.decide(
        tenant_id="tenant-a",
        approval_id=str(requested[0].payload["approval_id"]),
        decision=ApprovalStatus.REJECTED,
    )

    assert _decision(await task) == "deny"
    assert (await runs.get("tenant-a", "run-sdk")).status is RunStatus.RUNNING
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    event_types = [event.type for event in emitted]
    assert "tool.result" not in event_types
    assert "run.rejected" not in event_types
    assert event_types[-1] == "run.running"


@pytest.mark.asyncio
async def test_cancelled_sdk_wait_closes_pending_approval(tmp_path: Path) -> None:
    gate, approvals, runs, events, context = await _arrange(tmp_path)
    task = asyncio.create_task(
        _invoke(gate, context, _input("Bash", {"command": "pwd"}, "tool-timeout"))
    )
    requested = []
    for _ in range(20):
        emitted = await events.list_after("tenant-a", "run-sdk", 0)
        requested = [event for event in emitted if event.type == "approval.requested"]
        if requested:
            break
        await asyncio.sleep(0)
    assert requested
    approval_id = str(requested[0].payload["approval_id"])

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert emitted[-1].type == "approval.cancelled"
    assert emitted[-1].payload["reason"] == "tool authorization wait interrupted"
    assert (await runs.get("tenant-a", "run-sdk")).status is RunStatus.WAITING_APPROVAL
    with pytest.raises(ConflictError, match="already cancelled"):
        await approvals.decide(
            tenant_id="tenant-a",
            approval_id=approval_id,
            decision=ApprovalStatus.APPROVED,
        )


@pytest.mark.asyncio
async def test_approval_command_summary_redacts_inline_credentials(
    tmp_path: Path,
) -> None:
    gate, approvals, _, events, context = await _arrange(tmp_path)
    private_token = "private-command-token"
    task = asyncio.create_task(
        _invoke(
            gate,
            context,
            _input(
                "Bash",
                {"command": f"curl -H 'Authorization: Bearer {private_token}' /status"},
                "tool-secret-command",
            ),
        )
    )
    requested = []
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    for _ in range(20):
        emitted = await events.list_after("tenant-a", "run-sdk", 0)
        requested = [event for event in emitted if event.type == "approval.requested"]
        if requested:
            break
        await asyncio.sleep(0)
    assert requested

    approval_payload = requested[0].payload
    assert private_token not in repr(approval_payload)
    assert "[REDACTED]" in str(approval_payload["argument_summary"]["command"])
    tool_request = next(event for event in emitted if event.type == "tool.request")
    assert private_token not in repr(tool_request.payload)

    await approvals.decide(
        tenant_id="tenant-a",
        approval_id=str(approval_payload["approval_id"]),
        decision=ApprovalStatus.REJECTED,
    )
    assert _decision(await task) == "deny"
