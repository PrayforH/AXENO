"""Deterministic in-memory adapters for tests and no-Docker smoke runs."""

import asyncio
import hashlib
from collections import defaultdict, deque
from datetime import datetime
from typing import Literal

from harness.core.errors import ConflictError, EventSequenceConflictError, NotFoundError
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
from harness.core.ports import RunTask, StoredObject


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

    async def bind_claude_session_id(
        self, tenant_id: str, session_id: str, claude_session_id: str
    ) -> Session:
        if not claude_session_id:
            raise ValueError("claude_session_id must be non-empty")
        key = (tenant_id, session_id)
        async with self._lock:
            current = self._items.get(key)
            if current is None:
                raise NotFoundError(f"session not found: {session_id}")
            if current.claude_session_id is not None:
                if current.claude_session_id != claude_session_id:
                    raise ConflictError(
                        f"session {session_id} is already bound to another Claude session"
                    )
                return current
            updated = current.model_copy(
                update={"claude_session_id": claude_session_id}
            )
            self._items[key] = updated
            return updated


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
            if (
                current.status is not expected_status
                or current.fencing_token != updated.fencing_token - 1
            ):
                return False
            self._items[key] = updated
            return True

    async def list_for_sessions(
        self, tenant_id: str, session_ids: list[str], *, limit: int
    ) -> list[Run]:
        wanted = set(session_ids)
        matches = [
            run
            for (item_tenant, _), run in self._items.items()
            if item_tenant == tenant_id and run.session_id in wanted
        ]
        return sorted(matches, key=lambda run: (run.updated_at, run.run_id), reverse=True)[:limit]


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

    async def list_expired_pending(
        self, expires_at_or_before: datetime, *, limit: int
    ) -> list[ApprovalRequest]:
        items = [
            approval
            for approval in self._items.values()
            if approval.status is ApprovalStatus.PENDING
            and approval.expires_at <= expires_at_or_before
        ]
        return sorted(items, key=lambda approval: approval.expires_at)[:limit]

    async def list_for_runs(
        self, tenant_id: str, run_ids: list[str]
    ) -> list[ApprovalRequest]:
        wanted = set(run_ids)
        return sorted(
            (
                approval
                for (item_tenant, _), approval in self._items.items()
                if item_tenant == tenant_id and approval.run_id in wanted
            ),
            key=lambda approval: (approval.created_at, approval.approval_id),
            reverse=True,
        )


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
                raise EventSequenceConflictError(
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


class InMemoryUserMemoryRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], UserMemory] = {}
        self._lock = asyncio.Lock()

    async def add(self, memory: UserMemory) -> None:
        key = (memory.tenant_id, memory.user_id, memory.agent_name)
        async with self._lock:
            if key in self._items:
                raise ConflictError("user memory already exists")
            self._items[key] = memory

    async def get(self, tenant_id: str, user_id: str, agent_name: str) -> UserMemory | None:
        return self._items.get((tenant_id, user_id, agent_name))

    async def compare_and_set(self, expected_version: int, updated: UserMemory) -> bool:
        key = (updated.tenant_id, updated.user_id, updated.agent_name)
        async with self._lock:
            current = self._items.get(key)
            if current is None:
                raise NotFoundError("user memory not found")
            if current.version != expected_version:
                return False
            if updated.version != expected_version + 1:
                raise ConflictError("user memory version must increment by one")
            self._items[key] = updated
            return True

    async def delete(self, tenant_id: str, user_id: str, agent_name: str) -> None:
        self._items.pop((tenant_id, user_id, agent_name), None)


class InMemoryThreadFileRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ThreadFile] = {}
        self._lock = asyncio.Lock()

    async def add(self, file: ThreadFile) -> None:
        key = (file.tenant_id, file.file_id)
        async with self._lock:
            if key in self._items:
                raise ConflictError(f"thread file already exists: {file.file_id}")
            if file.parent_file_id is not None:
                parent = self._items.get((file.tenant_id, file.parent_file_id))
                if parent is None:
                    raise NotFoundError(f"parent thread file not found: {file.parent_file_id}")
                if (parent.user_id, parent.session_id) != (file.user_id, file.session_id):
                    raise ConflictError("derived file must share its parent's thread scope")
            self._items[key] = file

    async def get(self, tenant_id: str, file_id: str) -> ThreadFile:
        try:
            return self._items[(tenant_id, file_id)]
        except KeyError as error:
            raise NotFoundError(f"thread file not found: {file_id}") from error

    async def list_for_session(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> list[ThreadFile]:
        return [
            file
            for (item_tenant, _), file in self._items.items()
            if item_tenant == tenant_id
            and file.user_id == user_id
            and file.session_id == session_id
        ]

    async def list_children(self, tenant_id: str, parent_file_id: str) -> list[ThreadFile]:
        return [
            file
            for (item_tenant, _), file in self._items.items()
            if item_tenant == tenant_id and file.parent_file_id == parent_file_id
        ]


class InMemoryWorkspaceSnapshotRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], WorkspaceSnapshot] = {}
        self._lock = asyncio.Lock()

    async def add(self, snapshot: WorkspaceSnapshot) -> None:
        key = (snapshot.tenant_id, snapshot.snapshot_id)
        async with self._lock:
            if key in self._items:
                raise ConflictError(f"workspace snapshot already exists: {snapshot.snapshot_id}")
            self._items[key] = snapshot

    async def get(self, tenant_id: str, snapshot_id: str) -> WorkspaceSnapshot:
        try:
            return self._items[(tenant_id, snapshot_id)]
        except KeyError as error:
            raise NotFoundError(f"workspace snapshot not found: {snapshot_id}") from error

    async def latest(self, tenant_id: str, session_id: str) -> WorkspaceSnapshot | None:
        matches = [
            snapshot
            for (item_tenant, _), snapshot in self._items.items()
            if item_tenant == tenant_id and snapshot.session_id == session_id
        ]
        return max(matches, key=lambda item: item.created_at, default=None)


class InMemoryAguiThreadBindingRepository:
    def __init__(self) -> None:
        self._by_thread: dict[tuple[str, str, str], AguiThreadBinding] = {}
        self._by_session: dict[tuple[str, str, str], AguiThreadBinding] = {}
        self._lock = asyncio.Lock()

    async def add(self, binding: AguiThreadBinding) -> None:
        thread_key = (binding.tenant_id, binding.user_id, binding.thread_id)
        session_key = (binding.tenant_id, binding.user_id, binding.session_id)
        async with self._lock:
            if thread_key in self._by_thread or session_key in self._by_session:
                raise ConflictError("AG-UI thread binding already exists")
            self._by_thread[thread_key] = binding
            self._by_session[session_key] = binding

    async def get_by_thread(
        self, tenant_id: str, user_id: str, thread_id: str
    ) -> AguiThreadBinding:
        try:
            return self._by_thread[(tenant_id, user_id, thread_id)]
        except KeyError as error:
            raise NotFoundError(f"AG-UI thread binding not found: {thread_id}") from error

    async def get_by_session(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> AguiThreadBinding:
        try:
            return self._by_session[(tenant_id, user_id, session_id)]
        except KeyError as error:
            raise NotFoundError(f"AG-UI session binding not found: {session_id}") from error

    async def list_for_user(
        self, tenant_id: str, user_id: str, *, limit: int
    ) -> list[AguiThreadBinding]:
        matches = [
            binding
            for (item_tenant, item_user, _), binding in self._by_thread.items()
            if item_tenant == tenant_id and item_user == user_id
        ]
        return sorted(
            matches,
            key=lambda binding: (binding.updated_at, binding.thread_id),
            reverse=True,
        )[:limit]

    async def update_title(
        self,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        *,
        title: str,
        source: Literal["fallback", "model"],
        generated_at: datetime,
    ) -> AguiThreadBinding:
        thread_key = (tenant_id, user_id, thread_id)
        async with self._lock:
            try:
                binding = self._by_thread[thread_key]
            except KeyError as error:
                raise NotFoundError(
                    f"AG-UI thread binding not found: {thread_id}"
                ) from error
            if binding.title_updated_at is not None and binding.title_updated_at > generated_at:
                return binding
            updated = binding.model_copy(
                update={
                    "title": title,
                    "title_source": source,
                    "title_updated_at": generated_at,
                    "updated_at": max(binding.updated_at, generated_at),
                }
            )
            self._by_thread[thread_key] = updated
            self._by_session[(tenant_id, user_id, binding.session_id)] = updated
            return updated


class InMemoryTaskQueue:
    def __init__(self) -> None:
        self._items: deque[RunTask] = deque()
        self._pending: set[tuple[str, str]] = set()
        self._leased: set[tuple[str, str]] = set()

    async def enqueue(self, task: RunTask) -> None:
        key = (task.tenant_id, task.run_id)
        if key not in self._pending:
            self._pending.add(key)
            self._items.append(task)

    async def dequeue(self) -> RunTask | None:
        if not self._items:
            return None
        task = self._items.popleft()
        self._leased.add((task.tenant_id, task.run_id))
        return task

    async def acknowledge(self, task: RunTask) -> None:
        key = (task.tenant_id, task.run_id)
        self._leased.discard(key)
        self._pending.discard(key)

    async def retry(self, task: RunTask) -> None:
        key = (task.tenant_id, task.run_id)
        if key in self._leased:
            self._leased.remove(key)
            self._items.append(task)

    async def extend_lease(self, task: RunTask) -> None:
        del task
