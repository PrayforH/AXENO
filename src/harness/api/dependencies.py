"""FastAPI dependencies and the local in-memory composition root."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Header, HTTPException, Request

from harness.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryApprovalRepository,
    InMemoryArtifactRepository,
    InMemoryArtifactStore,
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryInputArtifactRepository,
    InMemoryRunRepository,
    InMemorySessionRepository,
    InMemoryTaskQueue,
    InMemoryThreadFileRepository,
    InMemoryUserMemoryRepository,
    InMemoryWorkspaceSnapshotRepository,
)
from harness.agui.service import AguiRunService
from harness.application.agents import AgentService
from harness.application.approvals import ApprovalService
from harness.application.artifacts import ArtifactService
from harness.application.events import EventService
from harness.application.file_catalog import FileCatalogService
from harness.application.input_artifacts import InputArtifactService
from harness.application.memory import UserMemoryService
from harness.application.runs import RunService
from harness.application.sessions import SessionService
from harness.application.workspaces import WorkspacePolicy, WorkspaceService
from harness.config import Settings
from harness.core.manifest import AgentManifestSnapshot
from harness.core.ports import EventRepository, TaskQueue
from harness.inputs.processors import DefaultInputProcessor
from harness.observability.provider import Observability, build_observability
from harness.policy.rules import PolicyEngine, default_policy_rules
from harness.runtime.base import AgentRuntime
from harness.runtime.cc_switch import load_cc_switch_claude_config
from harness.runtime.fake import FakeRuntime
from harness.runtime.registry_runtime import RegistryClaudeRuntime
from harness.runtime.sdk_tool_gate import SdkToolGate
from harness.sandbox.base import SandboxProvider
from harness.sandbox.daytona import (
    DaytonaSandboxProvider,
    SdkDaytonaClient,
)
from harness.sandbox.local import LocalSandboxProvider
from harness.worker.orchestrator import RunOrchestrator


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    user_id: str


@dataclass(frozen=True)
class ApiContainer:
    agents: AgentService
    sessions: SessionService
    runs: RunService
    approvals: ApprovalService
    artifacts: ArtifactService
    input_artifacts: InputArtifactService
    file_catalog: FileCatalogService
    memory: UserMemoryService
    events: EventRepository
    task_queue: TaskQueue
    observability: Observability
    runtime: AgentRuntime
    worker: RunOrchestrator
    agui: AguiRunService
    auto_execute: bool
    close: Callable[[], Awaitable[None]] | None = None


def build_memory_container(
    *,
    auto_execute: bool = False,
    settings: Settings | None = None,
) -> ApiContainer:
    resolved_settings = settings or Settings()
    registry = InMemoryAgentRegistry()
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    approvals = InMemoryApprovalRepository()
    artifact_repository = InMemoryArtifactRepository()
    input_artifact_repository = InMemoryInputArtifactRepository()
    memory_repository = InMemoryUserMemoryRepository()
    thread_file_repository = InMemoryThreadFileRepository()
    workspace_snapshot_repository = InMemoryWorkspaceSnapshotRepository()
    artifact_store = InMemoryArtifactStore()
    events = InMemoryEventRepository()
    bus = InMemoryEventBus()
    queue = InMemoryTaskQueue()
    observability = build_observability(resolved_settings)

    def clock() -> datetime:
        return datetime.now(UTC)

    def id_generator(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"

    event_service = EventService(events, bus, clock=clock, id_generator=id_generator)
    run_service = RunService(
        sessions,
        runs,
        queue,
        event_service,
        clock=clock,
        id_generator=id_generator,
        observability=observability,
    )
    session_service = SessionService(
        registry, sessions, clock=clock, id_generator=id_generator
    )
    approval_service = ApprovalService(
        runs=runs,
        approvals=approvals,
        events=event_service,
        clock=clock,
        id_generator=id_generator,
    )
    artifact_service = ArtifactService(
        runs=runs,
        repository=artifact_repository,
        store=artifact_store,
        id_generator=id_generator,
    )
    file_catalog_service = FileCatalogService(
        thread_file_repository,
        clock=clock,
        id_generator=id_generator,
    )
    input_artifact_service = InputArtifactService(
        repository=input_artifact_repository,
        store=artifact_store,
        id_generator=id_generator,
        clock=clock,
        processor=DefaultInputProcessor(),
        file_catalog=file_catalog_service,
    )
    memory_service = UserMemoryService(memory_repository, clock=clock)
    workspace_service = WorkspaceService(
        artifact_store, snapshots=workspace_snapshot_repository
    )

    async def workspace_policy_resolver(
        tenant_id: str, agent_name: str, agent_version: str
    ) -> WorkspacePolicy:
        version = await registry.get(tenant_id, agent_name, agent_version)
        manifest = AgentManifestSnapshot.model_validate(version.snapshot).manifest
        return WorkspacePolicy(
            restore_session=manifest.spec.workspace.restore_session,
            archive_on_complete=manifest.spec.workspace.archive_on_complete,
        )
    policy = PolicyEngine(default_policy_rules())
    if resolved_settings.sandbox_provider == "daytona":
        daytona_api_key = resolved_settings.daytona_api_key.get_secret_value()
        if not daytona_api_key:
            raise ValueError("HARNESS_DAYTONA_API_KEY is required for Daytona")
        sandbox: SandboxProvider = DaytonaSandboxProvider(
            client=SdkDaytonaClient.from_config(
                api_key=daytona_api_key,
                api_url=resolved_settings.daytona_api_url or None,
                target=resolved_settings.daytona_target or None,
            ),
            snapshot=resolved_settings.daytona_snapshot or None,
            remote_workspace_root=resolved_settings.daytona_remote_workspace_root,
            cli_version=resolved_settings.daytona_claude_cli_version,
            delete_on_destroy=resolved_settings.daytona_delete_on_destroy,
        )
    else:
        sandbox = LocalSandboxProvider()
    if resolved_settings.runtime == "fake":
        runtime: AgentRuntime = FakeRuntime()
    else:
        runtime = RegistryClaudeRuntime(
            registry=registry,
            config=load_cc_switch_claude_config(
                resolved_settings.cc_switch_settings_path
            ),
            tool_gate=SdkToolGate(
                policy=policy,
                approvals=approval_service,
                events=event_service,
            ),
            memory_service=memory_service,
            observability=observability,
        )
    worker = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=event_service,
        runtime=runtime,
        sandbox=sandbox,
        clock=clock,
        policy=policy,
        approvals=approval_service,
        workspaces=workspace_service,
        observability=observability,
        artifacts=artifact_service,
        input_artifacts=input_artifact_service,
        memory=memory_service,
        workspace_policy_resolver=workspace_policy_resolver,
        output_artifact_max_bytes=resolved_settings.output_artifact_max_bytes,
    )
    agui = AguiRunService(
        sessions=session_service,
        runs=run_service,
        input_artifacts=input_artifact_service,
    )
    return ApiContainer(
        agents=AgentService(registry, clock=clock),
        sessions=session_service,
        runs=run_service,
        approvals=approval_service,
        artifacts=artifact_service,
        input_artifacts=input_artifact_service,
        file_catalog=file_catalog_service,
        memory=memory_service,
        events=events,
        task_queue=queue,
        observability=observability,
        runtime=runtime,
        worker=worker,
        agui=agui,
        auto_execute=auto_execute,
    )


def get_container(request: Request) -> ApiContainer:
    return request.app.state.container


async def require_identity(
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
) -> Identity:
    if not tenant_id or not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "identity_required",
                "message": "X-Tenant-ID and X-User-ID headers are required",
            },
        )
    return Identity(tenant_id=tenant_id, user_id=user_id)
