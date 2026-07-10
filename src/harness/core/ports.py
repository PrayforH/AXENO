"""Framework-independent ports implemented by infrastructure adapters."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from harness.core.events import RunEvent
from harness.core.models import (
    AgentVersion,
    ApprovalRequest,
    ApprovalStatus,
    Run,
    RunStatus,
    Session,
)


class StoredObject(BaseModel):
    model_config = ConfigDict(frozen=True)

    object_key: str
    sha256: str
    size_bytes: int


class AgentRegistry(Protocol):
    async def add(self, version: AgentVersion) -> None: ...

    async def get(self, tenant_id: str, name: str, version: str) -> AgentVersion: ...


class SessionRepository(Protocol):
    async def add(self, session: Session) -> None: ...

    async def get(self, tenant_id: str, session_id: str) -> Session: ...


class RunRepository(Protocol):
    async def add(self, run: Run) -> None: ...

    async def get(self, tenant_id: str, run_id: str) -> Run: ...

    async def find_by_idempotency_key(
        self, tenant_id: str, session_id: str, idempotency_key: str
    ) -> Run | None: ...

    async def compare_and_set(self, expected_status: RunStatus, updated: Run) -> bool: ...


class ApprovalRepository(Protocol):
    async def add(self, approval: ApprovalRequest) -> None: ...

    async def get(self, tenant_id: str, approval_id: str) -> ApprovalRequest: ...

    async def find_by_tool_call(
        self, tenant_id: str, run_id: str, tool_call_id: str
    ) -> ApprovalRequest | None: ...

    async def compare_and_set(
        self, expected_status: ApprovalStatus, updated: ApprovalRequest
    ) -> bool: ...


class EventRepository(Protocol):
    async def append(self, event: RunEvent) -> None: ...

    async def list_after(
        self, tenant_id: str, run_id: str, after_sequence: int
    ) -> list[RunEvent]: ...


class EventBus(Protocol):
    async def publish(self, event: RunEvent) -> None: ...

    async def read(
        self, tenant_id: str, run_id: str, after_sequence: int = 0
    ) -> list[RunEvent]: ...


class ArtifactStore(Protocol):
    async def put(self, tenant_id: str, artifact_id: str, content: bytes) -> StoredObject: ...

    async def get(self, tenant_id: str, artifact_id: str) -> bytes: ...


class TaskQueue(Protocol):
    async def enqueue(self, run_id: str) -> None: ...

    async def dequeue(self) -> str | None: ...
