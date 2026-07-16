"""Framework-independent ports implemented by infrastructure adapters."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from harness.core.events import RunEvent
from harness.core.models import (
    AgentVersion,
    AguiThreadBinding,
    ApprovalRequest,
    ApprovalStatus,
    Artifact,
    InputArtifact,
    Run,
    RunStatus,
    Session,
    ThreadFile,
    UserMemory,
    WorkspaceSnapshot,
)


class StoredObject(BaseModel):
    model_config = ConfigDict(frozen=True)

    object_key: str
    sha256: str
    size_bytes: int


class RunTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    run_id: str


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


class ArtifactRepository(Protocol):
    async def add(self, artifact: Artifact) -> None: ...

    async def get(self, tenant_id: str, artifact_id: str) -> Artifact: ...

    async def update(self, artifact: Artifact) -> None: ...

    async def list_for_run(self, tenant_id: str, run_id: str) -> list[Artifact]: ...


class InputArtifactRepository(Protocol):
    async def add(self, artifact: InputArtifact) -> None: ...

    async def get(self, tenant_id: str, input_artifact_id: str) -> InputArtifact: ...

    async def update(self, artifact: InputArtifact) -> None: ...


class UserMemoryRepository(Protocol):
    async def add(self, memory: UserMemory) -> None: ...

    async def get(
        self, tenant_id: str, user_id: str, agent_name: str
    ) -> UserMemory | None: ...

    async def compare_and_set(self, expected_version: int, updated: UserMemory) -> bool: ...

    async def delete(self, tenant_id: str, user_id: str, agent_name: str) -> None: ...


class ThreadFileRepository(Protocol):
    async def add(self, file: ThreadFile) -> None: ...

    async def get(self, tenant_id: str, file_id: str) -> ThreadFile: ...

    async def list_for_session(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> list[ThreadFile]: ...

    async def list_children(self, tenant_id: str, parent_file_id: str) -> list[ThreadFile]: ...


class WorkspaceSnapshotRepository(Protocol):
    async def add(self, snapshot: WorkspaceSnapshot) -> None: ...

    async def get(self, tenant_id: str, snapshot_id: str) -> WorkspaceSnapshot: ...

    async def latest(self, tenant_id: str, session_id: str) -> WorkspaceSnapshot | None: ...


class AguiThreadBindingRepository(Protocol):
    async def add(self, binding: AguiThreadBinding) -> None: ...

    async def get_by_thread(
        self, tenant_id: str, user_id: str, thread_id: str
    ) -> AguiThreadBinding: ...

    async def get_by_session(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> AguiThreadBinding: ...


class TaskQueue(Protocol):
    async def enqueue(self, task: RunTask) -> None: ...

    async def dequeue(self) -> RunTask | None: ...

    async def acknowledge(self, task: RunTask) -> None: ...

    async def retry(self, task: RunTask) -> None: ...

    async def extend_lease(self, task: RunTask) -> None: ...
