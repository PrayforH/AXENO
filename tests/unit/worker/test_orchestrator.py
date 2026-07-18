import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from harness.adapters.memory import (
    InMemoryArtifactRepository,
    InMemoryArtifactStore,
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryRunRepository,
    InMemorySessionRepository,
)
from harness.application.artifacts import ArtifactService
from harness.application.events import EventService
from harness.config import Settings
from harness.core.models import Run, RunStatus, Session
from harness.observability.provider import Observability, build_observability
from harness.policy.profiles import default_policy_profiles
from harness.policy.rules import PolicyEngine, default_policy_rules
from harness.quota.models import QuotaResource, ReplaceQuotaPolicyRequest
from harness.quota.repositories import InMemoryQuotaRepository
from harness.quota.service import QuotaService
from harness.runtime.base import (
    RuntimeContext,
    RuntimeEvent,
    RuntimeExecutionTimeoutError,
    RuntimeResultError,
)
from harness.runtime.fake import FakeRuntime
from harness.sandbox.base import SandboxHandle, SandboxIsolation, SandboxProvider
from harness.sandbox.local import LocalSandboxProvider
from harness.worker.orchestrator import (
    PolicyResolver,
    RunOrchestrator,
    RuntimeAssetStager,
    read_runtime_artifact,
)

NOW = datetime(2026, 7, 11, tzinfo=UTC)


def test_runtime_artifact_reader_is_workspace_scoped_and_bounded(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "valid.txt").write_bytes(b"valid")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    (workspace / "link.txt").symlink_to(outside)

    path, content = read_runtime_artifact(
        workspace, "valid.txt", max_bytes=5
    )

    assert path == workspace / "valid.txt"
    assert content == b"valid"
    with pytest.raises(ValueError, match="escaped"):
        read_runtime_artifact(workspace, "../outside.txt", max_bytes=100)
    with pytest.raises(ValueError, match="escaped|regular file"):
        read_runtime_artifact(workspace, "link.txt", max_bytes=100)
    with pytest.raises(ValueError, match="size limit"):
        read_runtime_artifact(workspace, "valid.txt", max_bytes=4)


def ids() -> Callable[[str], str]:
    counters: dict[str, int] = {}

    def generate(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    return generate


class ToolRuntime(FakeRuntime):
    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        yield RuntimeEvent(type="message.start")
        yield RuntimeEvent(
            type="tool.request",
            payload={
                "tool_call_id": "task-1",
                "name": "Task",
                "arguments": {"subagent_type": "helper"},
            },
        )
        yield RuntimeEvent(
            type="tool.result",
            payload={"tool_call_id": "task-1", "content": "done", "is_error": False},
        )
        yield RuntimeEvent(type="message.completed")


class TimedOutRuntime(FakeRuntime):
    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        raise RuntimeExecutionTimeoutError("test runtime timeout")
        yield


class ErrorResultRuntime(FakeRuntime):
    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        yield RuntimeEvent(
            type="runtime.result",
            payload={"is_error": True, "subtype": "error_max_budget_usd"},
        )
        raise RuntimeResultError("error_max_budget_usd", api_error_status=429)


class ContentRejectedRuntime(FakeRuntime):
    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        yield RuntimeEvent(
            type="runtime.result",
            payload={"is_error": True, "subtype": "api_error_400"},
        )
        raise RuntimeResultError(
            "api_error_400",
            api_error_status=400,
            error_code="provider_content_rejected",
            user_message="模型服务拒绝了本轮上下文，请重新运行。",
        )


class CapturingRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[RuntimeContext] = []

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        self.contexts.append(context)
        async for event in super().execute(context):
            yield event


class SessionAwareRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[RuntimeContext] = []

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        self.contexts.append(context)
        sdk_session_id = context.session.claude_session_id or "sdk-session-1"
        yield RuntimeEvent(
            type="runtime.system",
            payload={"subtype": "init", "session_id": sdk_session_id},
        )
        yield RuntimeEvent(type="message.start")
        yield RuntimeEvent(type="message.delta", payload={"text": "ok"})
        yield RuntimeEvent(type="message.completed")
        yield RuntimeEvent(
            type="runtime.result",
            payload={"subtype": "success", "session_id": sdk_session_id},
        )


class FencingRefreshRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.runs: InMemoryRunRepository | None = None

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        assert self.runs is not None
        current = await self.runs.get(context.run.tenant_id, context.run.run_id)
        refreshed = current.model_copy(
            update={"fencing_token": current.fencing_token + 1}
        )
        assert await self.runs.compare_and_set(current.status, refreshed)
        yield RuntimeEvent(type="message.start")
        yield RuntimeEvent(type="message.delta", payload={"text": "approved"})
        yield RuntimeEvent(type="message.completed")


class WorkspaceOutputRuntime(FakeRuntime):
    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        output = context.workspace / "outputs" / "report.md"
        output.parent.mkdir(parents=True)
        output.write_text("verified output")
        yield RuntimeEvent(type="message.completed")


class ContainerSandboxProvider(LocalSandboxProvider):
    async def provision(self, run: Run) -> SandboxHandle:
        handle = await super().provision(run)
        return handle.model_copy(
            update={
                "provider": "daytona",
                "isolation_level": SandboxIsolation.CONTAINER,
            }
        )


class AssetCheckingSandboxProvider(LocalSandboxProvider):
    def __init__(self, root: Path) -> None:
        super().__init__(root=root)
        self.asset_was_ready = False

    async def prepare(self, handle: SandboxHandle) -> None:
        self.asset_was_ready = (
            handle.path / ".claude/skills/domain-core/SKILL.md"
        ).is_file()
        await super().prepare(handle)


class PausablePrepareSandboxProvider(LocalSandboxProvider):
    def __init__(self, root: Path) -> None:
        super().__init__(root=root)
        self.started = asyncio.Event()
        self.cancelled = False

    async def prepare(self, handle: SandboxHandle) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def arrange(
    tmp_path: Path,
    *,
    fail_runtime: bool = False,
    runtime_override: FakeRuntime | None = None,
    policy: PolicyEngine | None = None,
    observability: Observability | None = None,
    sandbox_override: SandboxProvider | None = None,
    runtime_asset_stager: RuntimeAssetStager | None = None,
    policy_resolver: PolicyResolver | None = None,
    enable_artifacts: bool = False,
    credential_revoker: Callable[[str, str], Awaitable[None]] | None = None,
    quotas: QuotaService | None = None,
):
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    event_repository = InMemoryEventRepository()
    runtime = runtime_override or FakeRuntime(fail=fail_runtime)
    sandbox = sandbox_override or LocalSandboxProvider(root=tmp_path)
    session = Session(
        session_id="session-1",
        tenant_id="tenant-a",
        user_id="user-1",
        agent_name="echo-agent",
        agent_version="1.0.0",
        created_at=NOW,
    )
    run = Run(
        run_id="run-1",
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        status=RunStatus.QUEUED,
        idempotency_key="idem-1",
        created_at=NOW,
        updated_at=NOW,
        input={"prompt": "hello harness"},
    )
    await sessions.add(session)
    await runs.add(run)
    artifact_service = (
        ArtifactService(
            runs=runs,
            repository=InMemoryArtifactRepository(),
            store=InMemoryArtifactStore(),
            id_generator=ids(),
        )
        if enable_artifacts
        else None
    )
    orchestrator = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=EventService(
            event_repository,
            InMemoryEventBus(),
            clock=lambda: NOW,
            id_generator=ids(),
        ),
        runtime=runtime,
        sandbox=sandbox,
        clock=lambda: NOW,
        policy=policy,
        observability=observability,
        runtime_asset_stager=runtime_asset_stager,
        policy_resolver=policy_resolver,
        artifacts=artifact_service,
        credential_revoker=credential_revoker,
        quotas=quotas,
    )
    return orchestrator, runtime, runs, event_repository


@pytest.mark.asyncio
async def test_worker_admission_rejects_unadmitted_run_before_sandbox_and_converges_failed(
    tmp_path: Path,
) -> None:
    quotas = QuotaService(InMemoryQuotaRepository())
    await quotas.replace_policy(
        tenant_id="tenant-a",
        user_id="owner-a",
        policy_id="tenant-default",
        request=ReplaceQuotaPolicyRequest(
            expectedRevision=0,
            limits={QuotaResource.CONCURRENT_RUNS: 1},
        ),
    )
    await quotas.reserve(
        tenant_id="tenant-a",
        resource=QuotaResource.CONCURRENT_RUNS,
        amount=1,
        subject_id="another-run",
        idempotency_key="another-run:concurrency",
    )
    orchestrator, _, _, events = await arrange(tmp_path, quotas=quotas)

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.FAILED
    assert result.error_code == "quota_exceeded_concurrent_runs"
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert [event.type for event in emitted] == ["run.provisioning", "run.failed"]


@pytest.mark.asyncio
async def test_run_completion_revokes_every_run_scoped_credential(
    tmp_path: Path,
) -> None:
    revoked: list[tuple[str, str]] = []

    async def revoke(tenant_id: str, run_id: str) -> None:
        revoked.append((tenant_id, run_id))

    orchestrator, _, _, _ = await arrange(
        tmp_path,
        credential_revoker=revoke,
    )

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.SUCCEEDED
    assert revoked == [("tenant-a", "run-1")]


@pytest.mark.asyncio
async def test_daytona_workspace_outputs_are_published_as_artifacts(
    tmp_path: Path,
) -> None:
    orchestrator, _, _, events = await arrange(
        tmp_path,
        runtime_override=WorkspaceOutputRuntime(),
        sandbox_override=ContainerSandboxProvider(root=tmp_path),
        enable_artifacts=True,
    )

    completed = await orchestrator.execute("tenant-a", "run-1")
    recorded = await events.list_after("tenant-a", "run-1", 0)
    artifact_events = [event for event in recorded if event.type == "artifact.ready"]

    assert completed.status is RunStatus.SUCCEEDED
    assert len(artifact_events) == 1
    assert artifact_events[0].payload["name"] == "report.md"
    assert artifact_events[0].payload["source"] == "workspace-output"


@pytest.mark.asyncio
async def test_runtime_assets_are_staged_before_sandbox_prepare(tmp_path: Path) -> None:
    sandbox = AssetCheckingSandboxProvider(tmp_path)

    async def stage_assets(
        _tenant_id: str,
        _agent_name: str,
        _agent_version: str,
        workspace: Path,
    ) -> tuple[str, ...]:
        target = workspace / ".claude/skills/domain-core"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("immutable")
        return ("domain-core",)

    orchestrator, _, _, events = await arrange(
        tmp_path,
        sandbox_override=sandbox,
        runtime_asset_stager=stage_assets,
    )

    await orchestrator.execute("tenant-a", "run-1")

    assert sandbox.asset_was_ready is True
    emitted = await events.list_after("tenant-a", "run-1", 0)
    staged = [event for event in emitted if event.type == "agent.assets.staged"]
    assert staged[0].payload == {"skills": ["domain-core"]}


@pytest.mark.asyncio
async def test_manifest_policy_resolver_overrides_generic_worker_policy(
    tmp_path: Path,
) -> None:
    async def resolve_policy(
        _tenant_id: str, _agent_name: str, _agent_version: str
    ) -> PolicyEngine:
        return default_policy_profiles().resolve("production-read-only")

    orchestrator, _, _, events = await arrange(
        tmp_path,
        runtime_override=ToolRuntime(),
        policy=PolicyEngine(default_policy_rules()),
        policy_resolver=resolve_policy,
    )

    await orchestrator.execute("tenant-a", "run-1")

    emitted = await events.list_after("tenant-a", "run-1", 0)
    denied = [
        event
        for event in emitted
        if event.type == "tool.result"
        and event.payload.get("error", {}).get("code") == "policy_denied"
    ]
    assert denied


@pytest.mark.asyncio
async def test_executes_run_and_cleans_sandbox(tmp_path: Path) -> None:
    orchestrator, runtime, runs, event_repository = await arrange(tmp_path)

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.SUCCEEDED
    assert runtime.execution_count == 1
    assert list(tmp_path.iterdir()) == []
    events = await event_repository.list_after("tenant-a", "run-1", 0)
    assert [event.type for event in events] == [
        "run.provisioning",
        "run.running",
        "message.start",
        "message.delta",
        "message.completed",
        "run.succeeded",
    ]
    assert (await runs.get("tenant-a", "run-1")).status is RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_terminal_transition_refreshes_fencing_after_inline_approval(
    tmp_path: Path,
) -> None:
    runtime = FencingRefreshRuntime()
    orchestrator, _, runs, events = await arrange(
        tmp_path, runtime_override=runtime
    )
    runtime.runs = runs

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.SUCCEEDED
    assert (await runs.get("tenant-a", "run-1")).status is RunStatus.SUCCEEDED
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert emitted[-1].type == "run.succeeded"


@pytest.mark.asyncio
async def test_next_run_receives_bound_claude_session_for_resume(
    tmp_path: Path,
) -> None:
    runtime = SessionAwareRuntime()
    orchestrator, _, runs, _ = await arrange(
        tmp_path,
        runtime_override=runtime,
    )

    first = await orchestrator.execute("tenant-a", "run-1")
    second_run = Run(
        run_id="run-2",
        session_id="session-1",
        tenant_id="tenant-a",
        status=RunStatus.QUEUED,
        idempotency_key="idem-2",
        created_at=NOW,
        updated_at=NOW,
        input={"prompt": "what did I say?"},
    )
    await runs.add(second_run)
    second = await orchestrator.execute("tenant-a", "run-2")

    assert first.status is RunStatus.SUCCEEDED
    assert second.status is RunStatus.SUCCEEDED
    assert runtime.contexts[0].session.claude_session_id is None
    assert runtime.contexts[1].session.claude_session_id == "sdk-session-1"


@pytest.mark.asyncio
async def test_runtime_timeout_has_a_distinct_terminal_status(tmp_path: Path) -> None:
    orchestrator, _, runs, events = await arrange(
        tmp_path, runtime_override=TimedOutRuntime()
    )

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.TIMED_OUT
    assert result.error_code == "runtime_timeout"
    assert (await runs.get("tenant-a", "run-1")).status is RunStatus.TIMED_OUT
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert emitted[-1].type == "run.timed_out"


@pytest.mark.asyncio
async def test_sdk_error_result_cannot_be_recorded_as_success(tmp_path: Path) -> None:
    orchestrator, _, runs, events = await arrange(
        tmp_path, runtime_override=ErrorResultRuntime()
    )

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.FAILED
    assert result.error_code == "runtime_result_error"
    assert (await runs.get("tenant-a", "run-1")).status is RunStatus.FAILED
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert emitted[-2].type == "runtime.result"
    assert emitted[-1].type == "run.failed"
    assert emitted[-1].payload == {
        "subtype": "error_max_budget_usd",
        "api_error_status": 429,
        "error_code": "runtime_result_error",
    }


@pytest.mark.asyncio
async def test_provider_content_rejection_keeps_a_safe_recoverable_failure(
    tmp_path: Path,
) -> None:
    orchestrator, _, runs, events = await arrange(
        tmp_path, runtime_override=ContentRejectedRuntime()
    )

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.FAILED
    assert result.error_code == "provider_content_rejected"
    assert (await runs.get("tenant-a", "run-1")).error_code == (
        "provider_content_rejected"
    )
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert emitted[-1].payload == {
        "subtype": "api_error_400",
        "api_error_status": 400,
        "message": "模型服务拒绝了本轮上下文，请重新运行。",
        "error_code": "provider_content_rejected",
    }


@pytest.mark.asyncio
async def test_passes_provisioned_sandbox_facts_to_runtime(tmp_path: Path) -> None:
    runtime = CapturingRuntime()
    orchestrator, _, _, event_repository = await arrange(
        tmp_path,
        runtime_override=runtime,
        sandbox_override=ContainerSandboxProvider(root=tmp_path),
    )

    await orchestrator.execute("tenant-a", "run-1")

    assert len(runtime.contexts) == 1
    assert runtime.contexts[0].sandbox_provider == "daytona"
    assert runtime.contexts[0].sandbox_isolation is SandboxIsolation.CONTAINER
    assert runtime.contexts[0].assistant_message_id.startswith("assistant-run-1-")
    events = await event_repository.list_after("tenant-a", "run-1", 0)
    started = next(event for event in events if event.type == "message.start")
    assert started.payload["message_id"] == runtime.contexts[0].assistant_message_id


@pytest.mark.asyncio
async def test_executes_run_with_stage_level_traces(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )
    orchestrator, _, _, _ = await arrange(
        tmp_path, observability=observability
    )

    await orchestrator.execute("tenant-a", "run-1")

    spans = exporter.get_finished_spans()
    assert {span.name for span in spans} >= {
        "harness.worker.run",
        "harness.sandbox.provision",
        "harness.memory.load",
        "harness.input.process",
        "harness.sandbox.prepare",
        "harness.runtime.execute",
        "harness.sandbox.collect",
        "harness.sandbox.destroy",
    }
    assert all(
        span.attributes is not None
        and span.attributes["langfuse.session.id"] == "session-1"
        and span.attributes["langfuse.trace.metadata.run_id"] == "run-1"
        for span in spans
        if span.name.startswith("harness.")
    )


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_execute_twice(tmp_path: Path) -> None:
    orchestrator, runtime, _, _ = await arrange(tmp_path)

    first = await orchestrator.execute("tenant-a", "run-1")
    second = await orchestrator.execute("tenant-a", "run-1")

    assert first == second
    assert runtime.execution_count == 1


@pytest.mark.asyncio
async def test_runtime_failure_marks_run_failed_and_cleans_sandbox(tmp_path: Path) -> None:
    orchestrator, runtime, _, event_repository = await arrange(tmp_path, fail_runtime=True)

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.FAILED
    assert result.error_code == "runtime_error"
    assert runtime.execution_count == 1
    assert list(tmp_path.iterdir()) == []
    events = await event_repository.list_after("tenant-a", "run-1", 0)
    assert events[-1].type == "run.failed"


class PausableRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.resume = asyncio.Event()

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        self.started.set()
        yield RuntimeEvent(type="message.start")
        await self.resume.wait()
        yield RuntimeEvent(type="message.delta", payload={"text": "too late"})


class BackgroundSubRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        yield RuntimeEvent(
            type="subagent.started",
            payload={
                "event_schema": "harness.subagent.v1",
                "task_id": "background-one",
                "alias": "researcher",
                "agent_name": "helper",
                "agent_version": "1.0.0",
                "policy_profile": "read-only",
                "depth": 1,
            },
        )
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class FailureAfterSubRuntime(FakeRuntime):
    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        yield RuntimeEvent(
            type="subagent.started",
            payload={
                "event_schema": "harness.subagent.v1",
                "task_id": "failed-child",
                "alias": "researcher",
                "agent_name": "helper",
                "agent_version": "1.0.0",
                "policy_profile": "read-only",
                "depth": 1,
            },
        )
        raise RuntimeError("injected parent failure")


class ContextBoundRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self._marker: ContextVar[str] = ContextVar("runtime_context_marker")
        self.closed_cleanly = False

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        token = self._marker.set("active")
        try:
            yield RuntimeEvent(type="message.start")
            await asyncio.sleep(0)
            yield RuntimeEvent(type="message.completed")
        finally:
            self._marker.reset(token)
            self.closed_cleanly = True


@pytest.mark.asyncio
async def test_policy_keeps_tool_request_for_ui_before_decision(tmp_path: Path) -> None:
    orchestrator, _, _, event_repository = await arrange(
        tmp_path,
        runtime_override=ToolRuntime(),
        policy=PolicyEngine(default_policy_rules()),
    )

    result = await orchestrator.execute("tenant-a", "run-1")

    events = await event_repository.list_after("tenant-a", "run-1", 0)
    tool_events = [event.type for event in events if event.type.startswith("tool.")]
    request = next(event for event in events if event.type == "tool.request")
    assert result.status is RunStatus.SUCCEEDED
    assert tool_events == ["tool.request", "tool.allowed", "tool.result"]
    assert request.payload["message_id"] == next(
        event.payload["message_id"] for event in events if event.type == "message.start"
    )


@pytest.mark.asyncio
async def test_cancellation_during_runtime_stops_at_next_event_boundary(
    tmp_path: Path,
) -> None:
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    events = InMemoryEventRepository()
    runtime = PausableRuntime()
    session = Session(
        session_id="session-1",
        tenant_id="tenant-a",
        user_id="user-1",
        agent_name="echo-agent",
        agent_version="1.0.0",
        created_at=NOW,
    )
    run = Run(
        run_id="run-1",
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        status=RunStatus.QUEUED,
        idempotency_key="cancel-boundary",
        created_at=NOW,
        updated_at=NOW,
    )
    await sessions.add(session)
    await runs.add(run)
    orchestrator = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=EventService(events, InMemoryEventBus(), clock=lambda: NOW, id_generator=ids()),
        runtime=runtime,
        sandbox=LocalSandboxProvider(root=tmp_path),
        clock=lambda: NOW,
    )

    execution = asyncio.create_task(orchestrator.execute("tenant-a", "run-1"))
    await runtime.started.wait()
    while (await runs.get("tenant-a", "run-1")).status is not RunStatus.RUNNING:
        await asyncio.sleep(0)
    current = await runs.get("tenant-a", "run-1")
    cancelling = current.model_copy(
        update={
            "status": RunStatus.CANCELLING,
            "fencing_token": current.fencing_token + 1,
        }
    )
    assert await runs.compare_and_set(RunStatus.RUNNING, cancelling)
    runtime.resume.set()

    result = await execution
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert result.status is RunStatus.CANCELLED
    assert "message.delta" not in [item.type for item in emitted]


@pytest.mark.asyncio
async def test_cancellation_interrupts_background_sub_and_emits_child_terminal(
    tmp_path: Path,
) -> None:
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    events = InMemoryEventRepository()
    runtime = BackgroundSubRuntime()
    session = Session(
        session_id="session-1",
        tenant_id="tenant-a",
        user_id="user-1",
        agent_name="echo-agent",
        agent_version="1.0.0",
        created_at=NOW,
    )
    run = Run(
        run_id="run-1",
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        status=RunStatus.QUEUED,
        idempotency_key="cancel-background",
        created_at=NOW,
        updated_at=NOW,
    )
    await sessions.add(session)
    await runs.add(run)
    orchestrator = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=EventService(
            events, InMemoryEventBus(), clock=lambda: NOW, id_generator=ids()
        ),
        runtime=runtime,
        sandbox=LocalSandboxProvider(root=tmp_path),
        clock=lambda: NOW,
        cancellation_poll_interval_seconds=0.01,
    )

    execution = asyncio.create_task(orchestrator.execute("tenant-a", "run-1"))
    await runtime.started.wait()
    current = await runs.get("tenant-a", "run-1")
    cancelling = current.model_copy(
        update={
            "status": RunStatus.CANCELLING,
            "fencing_token": current.fencing_token + 1,
        }
    )
    assert await runs.compare_and_set(RunStatus.RUNNING, cancelling)

    result = await asyncio.wait_for(execution, timeout=1)
    emitted = await events.list_after("tenant-a", "run-1", 0)
    child_terminal = next(
        event for event in emitted if event.type == "subagent.failed"
    )

    assert result.status is RunStatus.CANCELLED
    assert runtime.cancelled is True
    assert child_terminal.payload["task_id"] == "background-one"
    assert child_terminal.payload["error_code"] == "parent_cancelled"
    assert emitted[-1].type == "run.cancelled"


@pytest.mark.asyncio
async def test_parent_failure_emits_terminal_for_every_started_subagent(
    tmp_path: Path,
) -> None:
    orchestrator, _, _, events = await arrange(
        tmp_path,
        runtime_override=FailureAfterSubRuntime(),
    )

    result = await orchestrator.execute("tenant-a", "run-1")
    emitted = await events.list_after("tenant-a", "run-1", 0)
    child_terminal = next(
        event for event in emitted if event.type == "subagent.failed"
    )

    assert result.status is RunStatus.FAILED
    assert child_terminal.payload["task_id"] == "failed-child"
    assert child_terminal.payload["error_code"] == "parent_failed"
    assert emitted.index(child_terminal) < len(emitted) - 1
    assert emitted[-1].type == "run.failed"


@pytest.mark.asyncio
async def test_cancellation_polling_keeps_runtime_context_on_one_producer_task(
    tmp_path: Path,
) -> None:
    runtime = ContextBoundRuntime()
    orchestrator, _, _, _ = await arrange(tmp_path, runtime_override=runtime)

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.SUCCEEDED
    assert runtime.closed_cleanly is True


@pytest.mark.asyncio
async def test_cancellation_interrupts_sandbox_prepare(tmp_path: Path) -> None:
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    events = InMemoryEventRepository()
    sandbox = PausablePrepareSandboxProvider(tmp_path)
    session = Session(
        session_id="session-1",
        tenant_id="tenant-a",
        user_id="user-1",
        agent_name="echo-agent",
        agent_version="1.0.0",
        created_at=NOW,
    )
    run = Run(
        run_id="run-1",
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        status=RunStatus.QUEUED,
        idempotency_key="cancel-prepare",
        created_at=NOW,
        updated_at=NOW,
    )
    await sessions.add(session)
    await runs.add(run)
    orchestrator = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=EventService(
            events,
            InMemoryEventBus(),
            clock=lambda: NOW,
            id_generator=ids(),
        ),
        runtime=FakeRuntime(),
        sandbox=sandbox,
        clock=lambda: NOW,
        cancellation_poll_interval_seconds=0.01,
    )

    execution = asyncio.create_task(orchestrator.execute("tenant-a", "run-1"))
    await sandbox.started.wait()
    current = await runs.get("tenant-a", "run-1")
    assert current.status is RunStatus.PROVISIONING
    cancelling = current.model_copy(
        update={
            "status": RunStatus.CANCELLING,
            "fencing_token": current.fencing_token + 1,
        }
    )
    assert await runs.compare_and_set(RunStatus.PROVISIONING, cancelling)

    result = await asyncio.wait_for(execution, timeout=1)
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert result.status is RunStatus.CANCELLED
    assert sandbox.cancelled is True
    assert [item.type for item in emitted][-1] == "run.cancelled"


@pytest.mark.asyncio
async def test_recovered_provisioning_run_is_reclaimed_and_completed(
    tmp_path: Path,
) -> None:
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    events = InMemoryEventRepository()
    session = Session(
        session_id="session-1",
        tenant_id="tenant-a",
        user_id="user-1",
        agent_name="echo-agent",
        agent_version="1.0.0",
        created_at=NOW,
    )
    run = Run(
        run_id="run-1",
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        status=RunStatus.PROVISIONING,
        fencing_token=1,
        idempotency_key="recover-provisioning",
        created_at=NOW,
        updated_at=NOW,
    )
    await sessions.add(session)
    await runs.add(run)
    orchestrator = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=EventService(
            events,
            InMemoryEventBus(),
            clock=lambda: NOW,
            id_generator=ids(),
        ),
        runtime=FakeRuntime(),
        sandbox=LocalSandboxProvider(root=tmp_path),
        clock=lambda: NOW,
    )

    result = await orchestrator.execute("tenant-a", "run-1")
    emitted = await events.list_after("tenant-a", "run-1", 0)

    assert result.status is RunStatus.SUCCEEDED
    assert result.fencing_token == 4
    assert [item.type for item in emitted] == [
        "run.recovered",
        "run.running",
        "message.start",
        "message.delta",
        "message.completed",
        "run.succeeded",
    ]
