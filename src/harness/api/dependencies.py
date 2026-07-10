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
    InMemoryRunRepository,
    InMemorySessionRepository,
    InMemoryTaskQueue,
)
from harness.application.agents import AgentService
from harness.application.approvals import ApprovalService
from harness.application.artifacts import ArtifactService
from harness.application.events import EventService
from harness.application.runs import RunService
from harness.application.sessions import SessionService


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
    events: InMemoryEventRepository


def build_memory_container() -> ApiContainer:
    registry = InMemoryAgentRegistry()
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    approvals = InMemoryApprovalRepository()
    artifact_repository = InMemoryArtifactRepository()
    artifact_store = InMemoryArtifactStore()
    events = InMemoryEventRepository()
    bus = InMemoryEventBus()
    queue = InMemoryTaskQueue()

    def clock() -> datetime:
        return datetime.now(UTC)

    def id_generator(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"

    event_service = EventService(events, bus, clock=clock, id_generator=id_generator)
    return ApiContainer(
        agents=AgentService(registry, clock=clock),
        sessions=SessionService(registry, sessions, clock=clock, id_generator=id_generator),
        runs=RunService(
            sessions,
            runs,
            queue,
            event_service,
            clock=clock,
            id_generator=id_generator,
        ),
        approvals=ApprovalService(
            runs=runs,
            approvals=approvals,
            events=event_service,
            clock=clock,
            id_generator=id_generator,
        ),
        artifacts=ArtifactService(
            runs=runs,
            repository=artifact_repository,
            store=artifact_store,
            id_generator=id_generator,
        ),
        events=events,
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
