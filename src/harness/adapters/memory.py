"""Deterministic in-memory adapters for tests and no-Docker smoke runs."""

import asyncio
import hashlib
from collections import defaultdict, deque

from harness.core.errors import ConflictError, NotFoundError
from harness.core.events import RunEvent
from harness.core.models import (
    AgentVersion,
    ApprovalRequest,
    ApprovalStatus,
    Artifact,
    InputArtifact,
    Run,
    RunStatus,
    Session,
)
from harness.core.ports import StoredObject


class InMemoryAgentRegistry:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], AgentVersion] = {}
        self._lock = asyncio.Lock()

    async def add(self, version: AgentVersion) -> None:
        key = (version.tenant_id, version.name, version.version)
        async with self._lock:
            if key in self._items:
                raise ConflictError(
                    f"agent version already exists: {version.name}@{version.version}"
                )
            self._items[key] = version

    async def get(self, tenant_id: str, name: str, version: str) -> AgentVersion:
        try:
            return self._items[(tenant_id, name, version)]
        except KeyError as error:
            raise NotFoundError(f"agent version not found: {name}@{version}") from error


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], Session] = {}
        self._lock = asyncio.Lock()

    async def add(self, session: Session) -> None:
        key = (session.tenant_id, session.session_id)
        async with self._lock:
            if key in self._items:
                raise ConflictError(f"session already exists: {session.session_id}")
            self._items[key] = session

    async def get(self, tenant_id: str, session_id: str) -> Session:
        try:
            return self._items[(tenant_id, session_id)]
        except KeyError as error:
            raise NotFoundError(f"session not found: {session_id}") from error


class InMemoryRunRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], Run] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._lock = asyncio.Lock()

    async def add(self, run: Run) -> None:
        key = (run.tenant_id, run.run_id)
        idem_key = (run.tenant_id, run.session_id, run.idempotency_key)
        async with self._lock:
            if key in self._items or idem_key in self._idempotency:
                raise ConflictError(f"run already exists: {run.run_id}")
            self._items[key] = run
            self._idempotency[idem_key] = run.run_id

    async def get(self, tenant_id: str, run_id: str) -> Run:
        try:
            return self._items[(tenant_id, run_id)]
        except KeyError as error:
            raise NotFoundError(f"run not found: {run_id}") from error

    async def find_by_idempotency_key(
        self, tenant_id: str, session_id: str, idempotency_key: str
    ) -> Run | None:
        run_id = self._idempotency.get((tenant_id, session_id, idempotency_key))
        return None if run_id is None else self._items[(tenant_id, run_id)]

    async def compare_and_set(self, expected_status: RunStatus, updated: Run) -> bool:
        key = (updated.tenant_id, updated.run_id)
        async with self._lock:
            current = self._items.get(key)
            if current is None:
                raise NotFoundError(f"run not found: {updated.run_id}")
            if current.status is not expected_status:
                return False
            self._items[key] = updated
            return True


class InMemoryApprovalRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ApprovalRequest] = {}
        self._by_tool: dict[tuple[str, str, str], str] = {}
        self._lock = asyncio.Lock()

    async def add(self, approval: ApprovalRequest) -> None:
        key = (approval.tenant_id, approval.approval_id)
        tool_key = (approval.tenant_id, approval.run_id, approval.tool_call_id)
        async with self._lock:
            if key in self._items or tool_key in self._by_tool:
                raise ConflictError(f"approval already exists: {approval.approval_id}")
            self._items[key] = approval
            self._by_tool[tool_key] = approval.approval_id

    async def get(self, tenant_id: str, approval_id: str) -> ApprovalRequest:
        try:
            return self._items[(tenant_id, approval_id)]
        except KeyError as error:
            raise NotFoundError(f"approval not found: {approval_id}") from error

    async def find_by_tool_call(
        self, tenant_id: str, run_id: str, tool_call_id: str
    ) -> ApprovalRequest | None:
        approval_id = self._by_tool.get((tenant_id, run_id, tool_call_id))
        return None if approval_id is None else self._items[(tenant_id, approval_id)]

    async def compare_and_set(
        self, expected_status: ApprovalStatus, updated: ApprovalRequest
    ) -> bool:
        key = (updated.tenant_id, updated.approval_id)
        async with self._lock:
            current = self._items.get(key)
            if current is None:
                raise NotFoundError(f"approval not found: {updated.approval_id}")
            if current.status is not expected_status:
                return False
            self._items[key] = updated
            return True


class InMemoryEventRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], list[RunEvent]] = defaultdict(list)
        self._by_id: dict[str, RunEvent] = {}
        self._lock = asyncio.Lock()

    async def append(self, event: RunEvent) -> None:
        async with self._lock:
            existing = self._by_id.get(event.event_id)
            if existing is not None:
                if existing != event:
                    raise ConflictError(
                        f"event id already contains different data: {event.event_id}"
                    )
                return
            key = (event.tenant_id, event.run_id)
            expected_sequence = len(self._items[key]) + 1
            if event.sequence != expected_sequence:
                raise ConflictError(
                    f"event sequence must be {expected_sequence}, got {event.sequence}"
                )
            self._items[key].append(event)
            self._by_id[event.event_id] = event

    async def list_after(self, tenant_id: str, run_id: str, after_sequence: int) -> list[RunEvent]:
        return [
            event for event in self._items[(tenant_id, run_id)] if event.sequence > after_sequence
        ]


class InMemoryEventBus:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], list[RunEvent]] = defaultdict(list)

    async def publish(self, event: RunEvent) -> None:
        events = self._items[(event.tenant_id, event.run_id)]
        if all(existing.event_id != event.event_id for existing in events):
            events.append(event)

    async def read(self, tenant_id: str, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
        return [
            event for event in self._items[(tenant_id, run_id)] if event.sequence > after_sequence
        ]


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], bytes] = {}

    async def put(self, tenant_id: str, artifact_id: str, content: bytes) -> StoredObject:
        self._items[(tenant_id, artifact_id)] = content
        return StoredObject(
            object_key=f"{tenant_id}/{artifact_id}",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    async def get(self, tenant_id: str, artifact_id: str) -> bytes:
        try:
            return self._items[(tenant_id, artifact_id)]
        except KeyError as error:
            raise NotFoundError(f"artifact not found: {artifact_id}") from error


class InMemoryArtifactRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], Artifact] = {}
        self._lock = asyncio.Lock()

    async def add(self, artifact: Artifact) -> None:
        key = (artifact.tenant_id, artifact.artifact_id)
        async with self._lock:
            if key in self._items:
                raise ConflictError(f"artifact already exists: {artifact.artifact_id}")
            self._items[key] = artifact

    async def get(self, tenant_id: str, artifact_id: str) -> Artifact:
        try:
            return self._items[(tenant_id, artifact_id)]
        except KeyError as error:
            raise NotFoundError(f"artifact not found: {artifact_id}") from error

    async def update(self, artifact: Artifact) -> None:
        key = (artifact.tenant_id, artifact.artifact_id)
        async with self._lock:
            if key not in self._items:
                raise NotFoundError(f"artifact not found: {artifact.artifact_id}")
            self._items[key] = artifact

    async def list_for_run(self, tenant_id: str, run_id: str) -> list[Artifact]:
        return [
            artifact
            for (item_tenant, _), artifact in self._items.items()
            if item_tenant == tenant_id and artifact.run_id == run_id
        ]


class InMemoryInputArtifactRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], InputArtifact] = {}
        self._lock = asyncio.Lock()

    async def add(self, artifact: InputArtifact) -> None:
        key = (artifact.tenant_id, artifact.input_artifact_id)
        async with self._lock:
            if key in self._items:
                raise ConflictError(
                    f"input artifact already exists: {artifact.input_artifact_id}"
                )
            self._items[key] = artifact

    async def get(self, tenant_id: str, input_artifact_id: str) -> InputArtifact:
        try:
            return self._items[(tenant_id, input_artifact_id)]
        except KeyError as error:
            raise NotFoundError(
                f"input artifact not found: {input_artifact_id}"
            ) from error

    async def update(self, artifact: InputArtifact) -> None:
        key = (artifact.tenant_id, artifact.input_artifact_id)
        async with self._lock:
            if key not in self._items:
                raise NotFoundError(
                    f"input artifact not found: {artifact.input_artifact_id}"
                )
            self._items[key] = artifact


class InMemoryTaskQueue:
    def __init__(self) -> None:
        self._items: deque[str] = deque()
        self._pending: set[str] = set()

    async def enqueue(self, run_id: str) -> None:
        if run_id not in self._pending:
            self._pending.add(run_id)
            self._items.append(run_id)

    async def dequeue(self) -> str | None:
        if not self._items:
            return None
        run_id = self._items.popleft()
        self._pending.remove(run_id)
        return run_id
