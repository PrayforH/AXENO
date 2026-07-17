"""Coordinates one Run across repositories, Sandbox and Agent runtime."""

import asyncio
import hashlib
import mimetypes
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
    Sequence,
)
from contextlib import AbstractContextManager, nullcontext, suppress
from pathlib import Path
from typing import Any, TypeVar, cast
from uuid import uuid4

from harness.application.approvals import ApprovalService
from harness.application.artifacts import ArtifactService
from harness.application.events import EventService
from harness.application.input_artifacts import InputArtifactService
from harness.application.memory import UserMemoryService
from harness.application.runs import RunQuotaPlan, RunQuotaPlanResolver
from harness.application.types import Clock
from harness.application.workspaces import (
    WorkspacePolicy,
    WorkspacePolicyResolver,
    WorkspaceService,
)
from harness.core.errors import ConflictError
from harness.core.models import ExecutionIdentity, Run, RunStatus, Session
from harness.core.ports import RunRepository, SessionRepository
from harness.core.state_machine import transition
from harness.observability.provider import Observability
from harness.observability.redaction import correlation_hash
from harness.policy.models import PolicyContext, PolicyDecision
from harness.policy.rules import PolicyEngine
from harness.quota.repositories import QuotaExceededError
from harness.quota.service import QuotaService
from harness.runtime.artifact_tools import ArtifactPublisher
from harness.runtime.audit_redaction import redact_tool_arguments
from harness.runtime.base import (
    AgentRuntime,
    RuntimeContext,
    RuntimeExecutionTimeoutError,
    RuntimeResultError,
)
from harness.runtime.input_redaction import (
    INPUT_CONTENT_REDACTION,
    STAGED_INPUT_READ_MARKER,
    redact_workspace_paths,
    staged_input_paths,
    staged_read_path,
)
from harness.sandbox.base import (
    SandboxCommandResult,
    SandboxHandle,
    SandboxIsolation,
    SandboxProvider,
)

RuntimeAssetStager = Callable[[str, str, str, Path], Awaitable[tuple[str, ...]]]
PolicyResolver = Callable[[str, str, str], Awaitable[PolicyEngine]]
RunQualityHook = Callable[[Run, Session, str], Awaitable[object]]
RunCredentialRevoker = Callable[[str, str], Awaitable[None]]
SandboxResolver = Callable[[str, Session], Awaitable[SandboxProvider]]
T = TypeVar("T")


class _RunCancellationRequestedError(RuntimeExecutionTimeoutError):
    """Internal control flow used to stop a long-running orchestration stage."""


def _bind_sandbox_command_executor(
    sandbox: SandboxProvider,
    handle: SandboxHandle,
) -> Callable[
    [Sequence[str], Mapping[str, str] | None, float],
    Awaitable[SandboxCommandResult],
]:
    async def execute(
        argv: Sequence[str],
        environment: Mapping[str, str] | None,
        timeout_seconds: float,
    ) -> SandboxCommandResult:
        return await sandbox.execute(
            handle,
            argv,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )

    return execute


def read_runtime_artifact(
    workspace: Path, relative_path: str, *, max_bytes: int
) -> tuple[Path, bytes]:
    """Validate and bounded-read an untrusted runtime artifact."""
    candidate = workspace / relative_path
    try:
        artifact_path = candidate.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        raise ValueError("runtime artifact file does not exist") from None
    if not artifact_path.is_relative_to(workspace.resolve()):
        raise ValueError("runtime artifact path escaped the workspace")
    if candidate.is_symlink() or not artifact_path.is_file():
        raise ValueError("runtime artifact must be a regular file")
    if artifact_path.stat().st_size > max_bytes:
        raise ValueError("runtime artifact exceeds the output size limit")
    with artifact_path.open("rb") as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("runtime artifact exceeds the output size limit")
    return artifact_path, content


class RunOrchestrator:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        runs: RunRepository,
        events: EventService,
        runtime: AgentRuntime,
        sandbox: SandboxProvider,
        clock: Clock,
        policy: PolicyEngine | None = None,
        approvals: ApprovalService | None = None,
        workspaces: WorkspaceService | None = None,
        observability: Observability | None = None,
        artifacts: ArtifactService | None = None,
        input_artifacts: InputArtifactService | None = None,
        memory: UserMemoryService | None = None,
        workspace_policy_resolver: WorkspacePolicyResolver | None = None,
        runtime_asset_stager: RuntimeAssetStager | None = None,
        policy_resolver: PolicyResolver | None = None,
        output_artifact_max_bytes: int = 50 * 1024 * 1024,
        cancellation_poll_interval_seconds: float = 0.25,
        quality_hook: RunQualityHook | None = None,
        credential_revoker: RunCredentialRevoker | None = None,
        sandbox_resolver: SandboxResolver | None = None,
        quotas: QuotaService | None = None,
        quota_plan_resolver: RunQuotaPlanResolver | None = None,
    ) -> None:
        self._sessions = sessions
        self._runs = runs
        self._events = events
        self._runtime = runtime
        self._sandbox = sandbox
        self._clock = clock
        self._policy = policy
        self._approvals = approvals
        self._workspaces = workspaces
        self._observability = observability
        self._artifacts = artifacts
        self._input_artifacts = input_artifacts
        self._memory = memory
        self._workspace_policy_resolver = workspace_policy_resolver
        self._runtime_asset_stager = runtime_asset_stager
        self._policy_resolver = policy_resolver
        self._output_artifact_max_bytes = output_artifact_max_bytes
        self._cancellation_poll_interval_seconds = cancellation_poll_interval_seconds
        self._quality_hook = quality_hook
        self._credential_revoker = credential_revoker
        self._sandbox_resolver = sandbox_resolver
        self._quotas = quotas
        self._quota_plan_resolver = quota_plan_resolver

    def _stage(
        self,
        name: str,
        attributes: Mapping[str, str | bool | int | float] | None = None,
    ) -> AbstractContextManager[None]:
        if self._observability is None:
            return nullcontext()
        return self._observability.span(name, attributes=attributes)

    async def _runtime_events(self, context: RuntimeContext) -> AsyncIterator[Any]:
        with self._stage(
            "harness.runtime.execute",
            {
                "run.id": context.run.run_id,
                "agent.name": context.session.agent_name,
                "agent.version": context.session.agent_version,
            },
        ):
            async for event in self._runtime.execute(context):
                yield event

    async def _cancellable_runtime_events(
        self, context: RuntimeContext
    ) -> AsyncGenerator[Any, None]:
        """Poll durable cancellation while the SDK waits on background children."""
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def produce() -> None:
            try:
                async for event in self._runtime_events(context):
                    await queue.put(("event", event))
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - forwarded to orchestrator
                await queue.put(("error", error))
            else:
                await queue.put(("done", None))

        producer = asyncio.create_task(produce())
        try:
            while True:
                try:
                    kind, value = await self._await_cancellable(
                        context.run.tenant_id,
                        context.run.run_id,
                        queue.get(),
                    )
                except _RunCancellationRequestedError:
                    # An event can be produced just before the durable cancel is
                    # observed. Surface already-produced lifecycle facts before
                    # propagating cancellation so started children get terminals.
                    while not queue.empty():
                        queued_kind, queued_value = queue.get_nowait()
                        if queued_kind == "event":
                            yield queued_value
                    raise
                if kind == "done":
                    return
                if kind == "error":
                    if not isinstance(value, Exception):
                        raise RuntimeError("runtime producer returned an invalid error")
                    raise value
                yield value
        finally:
            if not producer.done():
                producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer

    async def _fail_active_subagents(
        self,
        *,
        tenant_id: str,
        run: Run,
        error_code: str,
    ) -> None:
        """Give every started child a durable terminal before its parent terminates."""
        events = await self._events.list_after(tenant_id, run.run_id, 0)
        active: dict[str, dict[str, Any]] = {}
        for event in events:
            if not event.type.startswith("subagent."):
                continue
            task_id = event.payload.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            if event.type == "subagent.started":
                active[task_id] = event.payload
            elif event.type in {"subagent.completed", "subagent.failed"}:
                active.pop(task_id, None)
        for task_id, started in active.items():
            safe = {
                key: started[key]
                for key in (
                    "event_schema",
                    "alias",
                    "agent_name",
                    "agent_version",
                    "policy_profile",
                    "depth",
                    "parent_tool_use_id",
                )
                if key in started
            }
            await self._events.append(
                tenant_id=tenant_id,
                run_id=run.run_id,
                session_id=run.session_id,
                event_type="subagent.failed",
                payload={
                    **safe,
                    "task_id": task_id,
                    "status": "cancelled",
                    "error_code": error_code,
                },
            )

    def _workspace_output_fingerprints(self, workspace: Path) -> dict[str, str]:
        output_root = workspace / "outputs"
        if not output_root.is_dir():
            return {}
        fingerprints: dict[str, str] = {}
        remaining = self._output_artifact_max_bytes
        for path in sorted(output_root.rglob("*")):
            if not (path.is_symlink() or path.is_file()):
                continue
            if len(fingerprints) >= 100:
                raise ValueError("workspace outputs exceed the artifact count limit")
            relative = path.relative_to(workspace).as_posix()
            _, content = read_runtime_artifact(
                workspace,
                relative,
                max_bytes=remaining,
            )
            remaining -= len(content)
            fingerprints[relative] = hashlib.sha256(content).hexdigest()
        return fingerprints

    async def _publish_remote_outputs(
        self,
        *,
        tenant_id: str,
        run: Run,
        workspace: Path,
        baseline: Mapping[str, str],
    ) -> None:
        if self._artifacts is None:
            return
        output_root = workspace / "outputs"
        if not output_root.is_dir():
            return
        files: list[Path] = []
        for path in output_root.rglob("*"):
            if path.is_symlink() or path.is_file():
                files.append(path)
                if len(files) > 100:
                    raise ValueError("workspace outputs exceed the artifact count limit")
        remaining = self._output_artifact_max_bytes
        for path in sorted(files):
            relative = path.relative_to(workspace).as_posix()
            resolved, content = read_runtime_artifact(
                workspace,
                relative,
                max_bytes=remaining,
            )
            remaining -= len(content)
            if baseline.get(relative) == hashlib.sha256(content).hexdigest():
                continue
            artifact = await self._artifacts.upload(
                tenant_id=tenant_id,
                run_id=run.run_id,
                name=relative.removeprefix("outputs/"),
                media_type=(mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"),
                content=content,
            )
            payload = artifact.model_dump(mode="json")
            payload["source"] = "workspace-output"
            await self._events.append(
                tenant_id=tenant_id,
                run_id=run.run_id,
                session_id=run.session_id,
                event_type="artifact.ready",
                payload=payload,
            )

    async def _await_cancellable(
        self,
        tenant_id: str,
        run_id: str,
        operation: Awaitable[T],
    ) -> T:
        """Await a long stage while observing durable Run cancellation state."""
        task = asyncio.ensure_future(operation)
        try:
            while True:
                done, _ = await asyncio.wait(
                    {task}, timeout=self._cancellation_poll_interval_seconds
                )
                if task in done:
                    return await task
                latest = await self._runs.get(tenant_id, run_id)
                if latest.status in {RunStatus.CANCELLING, RunStatus.CANCELLED}:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise _RunCancellationRequestedError
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def _move(
        self,
        current: Run,
        target: RunStatus,
        *,
        error_code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Run:
        next_status = transition(current.status, target)
        updated = current.model_copy(
            update={
                "status": next_status,
                "updated_at": self._clock(),
                "fencing_token": current.fencing_token + 1,
                "error_code": error_code,
            }
        )
        if not await self._runs.compare_and_set(current.status, updated):
            raise ConflictError(f"stale worker attempted to update run: {current.run_id}")
        await self._events.append(
            tenant_id=current.tenant_id,
            run_id=current.run_id,
            session_id=current.session_id,
            event_type=f"run.{target.value}",
            payload=payload,
        )
        return updated

    async def _handle_unexpected_error(
        self,
        tenant_id: str,
        run_id: str,
        error: Exception,
    ) -> Run:
        latest = await self._runs.get(tenant_id, run_id)
        if latest.status is RunStatus.CANCELLING:
            return await self._move(latest, RunStatus.CANCELLED)
        if latest.status is RunStatus.CANCELLED:
            return latest
        if isinstance(error, ConflictError) and not isinstance(error, QuotaExceededError):
            return latest
        if latest.status.is_terminal:
            return latest
        await self._fail_active_subagents(
            tenant_id=tenant_id,
            run=latest,
            error_code="parent_failed",
        )
        return await self._move(
            latest,
            RunStatus.FAILED,
            error_code=(
                f"quota_exceeded_{error.resource.value}"
                if isinstance(error, QuotaExceededError)
                else "runtime_error"
            ),
            payload={"error_type": type(error).__name__},
        )

    async def _reclaim(self, current: Run) -> Run:
        reclaimed = current.model_copy(
            update={
                "updated_at": self._clock(),
                "fencing_token": current.fencing_token + 1,
            }
        )
        if not await self._runs.compare_and_set(current.status, reclaimed):
            raise ConflictError(f"run ownership changed while reclaiming: {current.run_id}")
        await self._events.append(
            tenant_id=current.tenant_id,
            run_id=current.run_id,
            session_id=current.session_id,
            event_type="run.recovered",
            payload={"from_status": current.status.value},
        )
        return reclaimed

    async def _ensure_quota_admission(self, tenant_id: str, run_id: str, session: Session) -> None:
        if self._quotas is None:
            return
        plan = (
            await self._quota_plan_resolver(
                tenant_id, session.agent_name, session.agent_version
            )
            if self._quota_plan_resolver is not None
            else RunQuotaPlan(None, None, 3600)
        )
        await self._quotas.ensure_run_admitted(
            tenant_id=tenant_id,
            run_id=run_id,
            agent_name=session.agent_name,
            environment=session.environment,
            max_budget_usd=plan.max_budget_usd,
            max_model_tokens=plan.max_model_tokens,
            ttl_seconds=plan.ttl_seconds,
        )

    async def _record_quota_result(
        self,
        tenant_id: str,
        run_id: str,
        session: Session,
        payload: Mapping[str, Any],
    ) -> None:
        if self._quotas is None:
            return
        raw_usage = payload.get("usage")
        await self._quotas.record_run_result(
            tenant_id=tenant_id,
            run_id=run_id,
            agent_name=session.agent_name,
            environment=session.environment,
            usage=(cast(dict[str, object], raw_usage) if isinstance(raw_usage, dict) else None),
            total_cost_usd=payload.get("total_cost_usd"),
        )

    async def _release_terminal_quota(self, result: Run) -> None:
        if result.status.is_terminal and self._quotas is not None:
            await self._quotas.release_subject(result.tenant_id, result.run_id)

    async def execute(self, tenant_id: str, run_id: str) -> Run:
        if self._observability is None:
            result = await self._execute(tenant_id, run_id)
            await self._release_terminal_quota(result)
            return result
        run = await self._runs.get(tenant_id, run_id)
        session = await self._sessions.get(tenant_id, run.session_id)
        correlation_attributes: dict[str, str] = {
            "langfuse.session.id": run.session_id,
            "langfuse.trace.metadata.run_id": run.run_id,
            "session.id": run.session_id,
            "agent.name": session.agent_name,
            "agent.version": session.agent_version,
        }
        if session.deployment_snapshot_id:
            correlation_attributes["deployment.snapshot.id"] = session.deployment_snapshot_id
        if session.environment:
            correlation_attributes["deployment.environment"] = session.environment
        eval_run_id = run.input.get("eval_run_id")
        if isinstance(eval_run_id, str) and eval_run_id:
            correlation_attributes["eval.run.id"] = eval_run_id
        with self._observability.bind_attributes(correlation_attributes):
            with self._observability.span(
                "harness.worker.run",
                carrier=run.trace_context,
                attributes={
                    "run.id": run_id,
                    "tenant.hash": correlation_hash(tenant_id),
                },
            ):
                result = await self._execute(tenant_id, run_id)
                await self._release_terminal_quota(result)
                trace_id = self._observability.current_trace_id()
                if result.status.is_terminal and self._quality_hook is not None:
                    try:
                        await self._quality_hook(result, session, trace_id or "")
                    except Exception:
                        # Quality export is fail-open for the Agent Run. Durable
                        # sync state and alerts are reconciled independently.
                        pass
                return result

    async def _execute(self, tenant_id: str, run_id: str) -> Run:
        run = await self._runs.get(tenant_id, run_id)
        if run.status.is_terminal:
            return run
        if run.status is RunStatus.CANCELLING:
            return await self._move(run, RunStatus.CANCELLED)
        if run.status is RunStatus.WAITING_APPROVAL:
            # The worker may receive a lease recovered from a process that was
            # waiting inline. A later approval decision enqueues a fresh task;
            # acknowledge this delivery instead of retrying it forever.
            return run
        is_resume = run.status is RunStatus.RUNNING
        is_provision_recovery = run.status is RunStatus.PROVISIONING
        if run.status is not RunStatus.QUEUED and not is_resume and not is_provision_recovery:
            raise ConflictError(f"run is already owned or paused: {run_id} ({run.status.value})")

        handle: SandboxHandle | None = None
        active_sandbox = self._sandbox
        try:
            if not is_resume:
                if is_provision_recovery:
                    run = await self._reclaim(run)
                else:
                    run = await self._move(run, RunStatus.PROVISIONING)
            else:
                run = await self._reclaim(run)
            session = await self._sessions.get(tenant_id, run.session_id)
            if self._sandbox_resolver is not None:
                active_sandbox = await self._sandbox_resolver(tenant_id, session)
            await self._ensure_quota_admission(tenant_id, run_id, session)
            with self._stage("harness.sandbox.provision", {"run.id": run_id}):
                handle = await self._await_cancellable(
                    tenant_id,
                    run_id,
                    active_sandbox.provision(run),
                )
            active_policy = (
                await self._policy_resolver(tenant_id, session.agent_name, session.agent_version)
                if self._policy_resolver is not None
                else self._policy
            )
            workspace_policy = (
                await self._workspace_policy_resolver(
                    tenant_id, session.agent_name, session.agent_version
                )
                if self._workspace_policy_resolver is not None
                else WorkspacePolicy()
            )
            if self._workspaces is not None and workspace_policy.restore_session:
                with self._stage("harness.workspace.restore", {"run.id": run_id}):
                    restored = await self._workspaces.restore_latest(
                        tenant_id=tenant_id,
                        session_id=session.session_id,
                        workspace=handle.path,
                    )
                if restored is not None:
                    await self._events.append(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        session_id=run.session_id,
                        event_type="workspace.restored",
                        payload=restored.model_dump(mode="json"),
                    )
            identity = ExecutionIdentity(
                tenant_id=session.tenant_id,
                user_id=session.user_id,
                project_id=session.agent_name,
                session_id=session.session_id,
                run_id=run.run_id,
                agent_name=session.agent_name,
                agent_version=session.agent_version,
            )
            with self._stage("harness.memory.load", {"run.id": run_id}):
                memory_projection = (
                    await self._memory.projection(identity) if self._memory is not None else ""
                )
            raw_input_artifact_ids: object = run.input.get("input_artifact_ids", [])
            if not isinstance(raw_input_artifact_ids, list):
                raise ValueError("run input_artifact_ids must be a list of strings")
            input_artifact_ids: list[str] = []
            for item in cast(list[object], raw_input_artifact_ids):
                if not isinstance(item, str):
                    raise ValueError("run input_artifact_ids must be a list of strings")
                input_artifact_ids.append(item)
            if input_artifact_ids and self._input_artifacts is None:
                raise RuntimeError("input artifact service is not configured")
            with self._stage(
                "harness.input.process",
                {"run.id": run_id, "input.count": len(input_artifact_ids)},
            ):
                staged_inputs = (
                    await self._input_artifacts.stage_for_run(
                        tenant_id=tenant_id,
                        user_id=session.user_id,
                        input_artifact_ids=input_artifact_ids,
                        workspace=handle.path,
                        identity=identity,
                    )
                    if self._input_artifacts is not None
                    else []
                )
            for staged in staged_inputs:
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    event_type="input.staged",
                    payload=staged.model_dump(mode="json"),
                )
            input_paths = staged_input_paths(
                handle.path,
                tuple(staged.path for staged in staged_inputs),
            )
            if self._runtime_asset_stager is not None:
                with self._stage("harness.agent.assets.stage", {"run.id": run_id}):
                    staged_skills = await self._runtime_asset_stager(
                        tenant_id,
                        session.agent_name,
                        session.agent_version,
                        handle.path,
                    )
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    event_type="agent.assets.staged",
                    payload={"skills": list(staged_skills)},
                )
            with self._stage("harness.sandbox.prepare", {"run.id": run_id}):
                await self._await_cancellable(
                    tenant_id,
                    run_id,
                    active_sandbox.prepare(handle),
                )
            staged_read_tool_calls: set[str] = set()
            if not is_resume:
                run = await self._move(run, RunStatus.RUNNING)
            else:
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    event_type="run.resumed",
                )

            async def sync_workspace() -> None:
                await active_sandbox.collect(handle)

            artifact_publisher = (
                ArtifactPublisher(
                    workspace=handle.path,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    artifacts=self._artifacts,
                    events=self._events,
                    sync_workspace=sync_workspace,
                    max_file_bytes=self._output_artifact_max_bytes,
                    observability=self._observability,
                )
                if self._artifacts is not None
                else None
            )
            context = RuntimeContext(
                run=run,
                session=session,
                workspace=handle.path,
                sandbox_provider=handle.provider,
                sandbox_isolation=handle.isolation_level,
                remote_workspace=handle.remote_workspace,
                assistant_message_id=f"assistant-{run_id}-{uuid4().hex}",
                input_files=tuple(
                    path for item in staged_inputs for path in (item.path, *item.processed_paths)
                ),
                identity=identity,
                memory_projection=memory_projection,
                processed_input_paths=tuple(
                    path for item in staged_inputs for path in item.processed_paths
                ),
                runtime_transport_factory=handle.runtime_transport_factory,
                sandbox_command_executor=(
                    _bind_sandbox_command_executor(active_sandbox, handle)
                    if handle.deferred_tool_execution
                    else None
                ),
                artifact_publisher=artifact_publisher,
            )
            output_baseline = (
                self._workspace_output_fingerprints(handle.path)
                if handle.isolation_level is SandboxIsolation.CONTAINER
                else {}
            )
            active_message_id: str | None = context.assistant_message_id
            runtime_events = self._cancellable_runtime_events(context)
            async for runtime_event in runtime_events:
                latest = await self._runs.get(tenant_id, run_id)
                if latest.status is RunStatus.CANCELLING:
                    if runtime_event.type == "subagent.started":
                        await self._events.append(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            session_id=run.session_id,
                            event_type=runtime_event.type,
                            payload=dict(runtime_event.payload),
                        )
                    await runtime_events.aclose()
                    await self._fail_active_subagents(
                        tenant_id=tenant_id,
                        run=latest,
                        error_code="parent_cancelled",
                    )
                    return await self._move(latest, RunStatus.CANCELLED)
                if latest.status.is_terminal:
                    await runtime_events.aclose()
                    return latest
                run = latest
                payload = dict(runtime_event.payload)
                if runtime_event.type == "runtime.result":
                    await self._record_quota_result(tenant_id, run_id, session, payload)
                if runtime_event.type in {"runtime.system", "runtime.result"}:
                    sdk_session_id = payload.get("session_id")
                    if isinstance(sdk_session_id, str) and sdk_session_id:
                        session = await self._sessions.bind_claude_session_id(
                            tenant_id,
                            session.session_id,
                            sdk_session_id,
                        )
                original_tool_arguments: dict[str, Any] | None = None
                if runtime_event.type == "tool.request":
                    raw_arguments = payload.get("arguments")
                    if isinstance(raw_arguments, dict):
                        original_tool_arguments = dict(cast(dict[str, Any], raw_arguments))
                    relative_input_path = staged_read_path(
                        payload,
                        workspace=handle.path,
                        staged_paths=input_paths,
                    )
                    if relative_input_path is not None:
                        tool_call_id = str(payload.get("tool_call_id", ""))
                        if tool_call_id:
                            staged_read_tool_calls.add(tool_call_id)
                        sanitized_arguments = dict(original_tool_arguments or {})
                        sanitized_arguments["file_path"] = relative_input_path
                        payload["arguments"] = sanitized_arguments
                        payload[STAGED_INPUT_READ_MARKER] = True
                elif runtime_event.type == "tool.result":
                    tool_call_id = str(payload.get("tool_call_id", ""))
                    redact_result = tool_call_id in staged_read_tool_calls
                    if not redact_result and tool_call_id:
                        prior_events = await self._events.list_after(
                            tenant_id,
                            run_id,
                            0,
                        )
                        matching_request = next(
                            (
                                event
                                for event in reversed(prior_events)
                                if event.type == "tool.request"
                                and str(event.payload.get("tool_call_id", "")) == tool_call_id
                            ),
                            None,
                        )
                        redact_result = bool(
                            matching_request
                            and matching_request.payload.get(STAGED_INPUT_READ_MARKER)
                        )
                    if redact_result:
                        payload["content"] = INPUT_CONTENT_REDACTION
                        payload["redacted"] = True
                payload = cast(
                    dict[str, Any],
                    redact_workspace_paths(payload, handle.path),
                )
                if runtime_event.type == "message.start":
                    active_message_id = str(
                        payload.get("message_id")
                        or active_message_id
                        or f"assistant-{run_id}-{uuid4().hex}"
                    )
                    payload["message_id"] = active_message_id
                elif runtime_event.type in {"message.delta", "message.completed"}:
                    active_message_id = str(
                        payload.get("message_id")
                        or active_message_id
                        or f"assistant-{run_id}-{uuid4().hex}"
                    )
                    payload["message_id"] = active_message_id
                elif runtime_event.type == "tool.request" and active_message_id is not None:
                    payload["message_id"] = active_message_id
                if runtime_event.type == "tool.request":
                    audit_arguments = payload.get("arguments")
                    if isinstance(audit_arguments, dict):
                        payload["arguments"] = redact_tool_arguments(
                            str(payload.get("name", "")),
                            cast(dict[str, Any], audit_arguments),
                        )
                if runtime_event.type == "artifact.output" and self._artifacts is not None:
                    if handle.isolation_level is SandboxIsolation.CONTAINER:
                        await active_sandbox.collect(handle)
                    relative_path = str(payload.get("path", ""))
                    artifact_path, artifact_content = read_runtime_artifact(
                        handle.path,
                        relative_path,
                        max_bytes=self._output_artifact_max_bytes,
                    )
                    with self._stage("harness.artifact.publish", {"run.id": run_id}):
                        artifact = await self._artifacts.upload(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            name=str(payload.get("name", artifact_path.name)),
                            media_type=str(payload.get("media_type", "application/octet-stream")),
                            content=artifact_content,
                        )
                    artifact_payload = artifact.model_dump(mode="json")
                    if active_message_id is not None:
                        artifact_payload["message_id"] = active_message_id
                    await self._events.append(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        session_id=run.session_id,
                        event_type="artifact.ready",
                        payload=artifact_payload,
                    )
                    continue
                if runtime_event.type == "tool.request" and active_policy is not None:
                    tool_name = str(payload.get("name", ""))
                    tool_call_id = str(payload.get("tool_call_id", ""))
                    arguments = original_tool_arguments
                    if arguments is None:
                        arguments = payload.get("arguments", {})
                    if not isinstance(arguments, dict):
                        arguments = {}
                    typed_arguments = cast(dict[str, Any], arguments)
                    # Keep the request in the durable event stream so AG-UI can
                    # pair progress and results even when policy makes the decision.
                    await self._events.append(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        session_id=run.session_id,
                        event_type="tool.request",
                        payload=payload,
                    )
                    result = active_policy.evaluate(
                        PolicyContext(
                            tenant_id=tenant_id,
                            agent_name=session.agent_name,
                            tool_name=tool_name,
                            arguments=typed_arguments,
                        )
                    )
                    if result.decision is PolicyDecision.DENY:
                        await self._events.append(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            session_id=run.session_id,
                            event_type="tool.result",
                            payload={
                                "tool_call_id": tool_call_id,
                                "is_error": True,
                                "error": {
                                    "code": "policy_denied",
                                    "message": result.reason,
                                },
                            },
                        )
                        continue
                    if result.decision is PolicyDecision.ASK:
                        if self._approvals is None:
                            raise RuntimeError("approval service is not configured")
                        approval = await self._approvals.request(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            tool_call_id=tool_call_id,
                            reason=result.reason,
                            message_id=active_message_id,
                        )
                        if approval.status.value == "pending":
                            if active_message_id is not None:
                                await self._events.append(
                                    tenant_id=tenant_id,
                                    run_id=run_id,
                                    session_id=run.session_id,
                                    event_type="message.completed",
                                    payload={"message_id": active_message_id},
                                )
                            await runtime_events.aclose()
                            return await self._runs.get(tenant_id, run_id)
                    await self._events.append(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        session_id=run.session_id,
                        event_type="tool.allowed",
                        payload={"tool_call_id": tool_call_id},
                    )
                    continue
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    event_type=runtime_event.type,
                    payload=payload,
                )
                if runtime_event.type == "message.completed":
                    active_message_id = None
            with self._stage("harness.sandbox.collect", {"run.id": run_id}):
                await active_sandbox.collect(handle)
            if handle.isolation_level is SandboxIsolation.CONTAINER:
                with self._stage("harness.artifact.publish_outputs", {"run.id": run_id}):
                    await self._publish_remote_outputs(
                        tenant_id=tenant_id,
                        run=run,
                        workspace=handle.path,
                        baseline=output_baseline,
                    )
            if self._workspaces is not None and workspace_policy.archive_on_complete:
                with self._stage("harness.workspace.archive", {"run.id": run_id}):
                    snapshot = await self._workspaces.archive(
                        tenant_id=tenant_id,
                        session_id=run.session_id,
                        workspace=handle.path,
                    )
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    event_type="workspace.archived",
                    payload=snapshot.model_dump(mode="json"),
                )
            latest = await self._runs.get(tenant_id, run_id)
            if latest.status is RunStatus.CANCELLING:
                return await self._move(latest, RunStatus.CANCELLED)
            if latest.status.is_terminal:
                return latest
            return await self._move(latest, RunStatus.SUCCEEDED)
        except RuntimeExecutionTimeoutError:
            latest = await self._runs.get(tenant_id, run_id)
            if latest.status is RunStatus.CANCELLING:
                await self._fail_active_subagents(
                    tenant_id=tenant_id,
                    run=latest,
                    error_code="parent_cancelled",
                )
                return await self._move(latest, RunStatus.CANCELLED)
            if latest.status.is_terminal:
                return latest
            await self._fail_active_subagents(
                tenant_id=tenant_id,
                run=latest,
                error_code="parent_timed_out",
            )
            return await self._move(
                latest,
                RunStatus.TIMED_OUT,
                error_code="runtime_timeout",
                payload={"timeout": "manifest runtime limit exceeded"},
            )
        except RuntimeResultError as error:
            latest = await self._runs.get(tenant_id, run_id)
            if latest.status is RunStatus.CANCELLING:
                return await self._move(latest, RunStatus.CANCELLED)
            if latest.status.is_terminal:
                return latest
            payload: dict[str, Any] = {"subtype": error.subtype}
            if error.api_error_status is not None:
                payload["api_error_status"] = error.api_error_status
            return await self._move(
                latest,
                RunStatus.FAILED,
                error_code="runtime_result_error",
                payload=payload,
            )
        except Exception as error:  # noqa: BLE001 - boundary converts failures to Run state
            return await self._handle_unexpected_error(tenant_id, run_id, error)
        finally:
            if self._credential_revoker is not None:
                await self._credential_revoker(tenant_id, run_id)
            if handle is not None:
                with self._stage("harness.sandbox.destroy", {"run.id": run_id}):
                    await active_sandbox.destroy(handle)
