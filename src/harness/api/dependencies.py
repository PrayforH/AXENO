"""FastAPI dependencies and the local in-memory composition root."""

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
)
from harness.agui.service import AguiRunService
from harness.application.agents import AgentService
from harness.application.approvals import ApprovalService
from harness.application.artifacts import ArtifactService
from harness.application.events import EventService
from harness.application.input_artifacts import InputArtifactService
from harness.application.runs import RunService
from harness.application.sessions import SessionService
from harness.application.workspaces import WorkspaceService
from harness.config import Settings
from harness.observability.provider import Observability, build_observability
from harness.policy.rules import PolicyEngine, default_policy_rules
from harness.runtime.base import AgentRuntime
from harness.runtime.cc_switch import load_cc_switch_claude_config
from harness.runtime.fake import FakeRuntime
from harness.runtime.registry_runtime import RegistryClaudeRuntime
from harness.runtime.sdk_tool_gate import SdkToolGate
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
    events: InMemoryEventRepository
    observability: Observability
    runtime: AgentRuntime
    worker: RunOrchestrator
    agui: AguiRunService
    auto_execute: bool


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
    input_artifact_service = InputArtifactService(
        repository=input_artifact_repository,
        store=artifact_store,
        id_generator=id_generator,
        clock=clock,
    )
    policy = PolicyEngine(default_policy_rules())
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
        )
    worker = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=event_service,
        runtime=runtime,
        sandbox=LocalSandboxProvider(),
        clock=clock,
        policy=policy,
        approvals=approval_service,
        workspaces=WorkspaceService(artifact_store),
        observability=observability,
        artifacts=artifact_service,
        input_artifacts=input_artifact_service,
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
        events=events,
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
