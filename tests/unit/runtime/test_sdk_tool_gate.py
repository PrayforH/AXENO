import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from claude_agent_sdk import PreToolUseHookInput
from claude_agent_sdk.types import SyncHookJSONOutput

from harness.adapters.memory import (
    InMemoryApprovalRepository,
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryRunRepository,
)
from harness.application.approvals import ApprovalService
from harness.application.events import EventService
from harness.core.models import ApprovalStatus, Run, RunStatus, Session
from harness.policy.rules import PolicyEngine, default_policy_rules
from harness.runtime.base import RuntimeContext
from harness.runtime.sdk_tool_gate import SdkToolGate

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _ids() -> Callable[[str], str]:
    count = 0

    def generate(prefix: str) -> str:
        nonlocal count
        count += 1
        return f"{prefix}-{count}"

    return generate


async def _arrange(tmp_path: Path):
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
    gate = SdkToolGate(
        policy=PolicyEngine(default_policy_rules()),
        approvals=approval_service,
        events=events,
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
    )
    return gate, approval_service, runs, event_repository, context


def _input(name: str, arguments: dict[str, object], tool_use_id: str):
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
            "agent_type": "",
        },
    )


async def _invoke(
    gate: SdkToolGate,
    context: RuntimeContext,
    hook_input: PreToolUseHookInput,
) -> SyncHookJSONOutput:
    matcher = gate.hooks(context)["PreToolUse"][0]
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
async def test_allows_read_before_tool_execution_and_emits_ordered_events(tmp_path: Path) -> None:
    gate, _, _, events, context = await _arrange(tmp_path)

    output = await _invoke(gate, context, _input("Read", {"file_path": "a.txt"}, "tool-1"))

    assert _decision(output) == "allow"
    emitted = await events.list_after("tenant-a", "run-sdk", 0)
    assert [event.type for event in emitted] == ["tool.request", "tool.allowed"]


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
    task = asyncio.create_task(
        _invoke(gate, context, _input("Bash", {"command": "ls"}, "tool-3"))
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
