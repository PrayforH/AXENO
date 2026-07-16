"""Thread-scoped catalog for original, derived and generated files."""

from typing import Any

from harness.application.types import Clock, IdGenerator
from harness.core.models import ExecutionIdentity, ThreadFile, ThreadFileKind
from harness.core.ports import ThreadFileRepository


class FileCatalogService:
    def __init__(
        self,
        repository: ThreadFileRepository,
        *,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._id_generator = id_generator

    async def record_original(
        self,
        *,
        identity: ExecutionIdentity,
        input_artifact_id: str,
        name: str,
        media_type: str,
        path: str,
        metadata: dict[str, Any] | None = None,
    ) -> ThreadFile:
        file = ThreadFile(
            file_id=self._id_generator("thread_file"),
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            session_id=identity.session_id,
            run_id=identity.run_id,
            kind=ThreadFileKind.ORIGINAL,
            name=name,
            media_type=media_type,
            path=path,
            created_at=self._clock(),
            input_artifact_id=input_artifact_id,
            metadata=metadata or {},
        )
        await self._repository.add(file)
        return file

    async def record_derived(
        self,
        *,
        identity: ExecutionIdentity,
        parent: ThreadFile,
        name: str,
        media_type: str,
        path: str,
        metadata: dict[str, Any] | None = None,
    ) -> ThreadFile:
        file = ThreadFile(
            file_id=self._id_generator("thread_file"),
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            session_id=identity.session_id,
            run_id=identity.run_id,
            kind=ThreadFileKind.DERIVED,
            name=name,
            media_type=media_type,
            path=path,
            created_at=self._clock(),
            parent_file_id=parent.file_id,
            metadata=metadata or {},
        )
        await self._repository.add(file)
        return file

    async def list_for_thread(self, identity: ExecutionIdentity) -> list[ThreadFile]:
        return await self.list_scope(
            identity.tenant_id, identity.user_id, identity.session_id
        )

    async def list_scope(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> list[ThreadFile]:
        return await self._repository.list_for_session(tenant_id, user_id, session_id)
