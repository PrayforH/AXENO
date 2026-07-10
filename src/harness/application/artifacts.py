"""Artifact metadata and object lifecycle use cases."""

from harness.application.types import IdGenerator
from harness.core.models import Artifact, ArtifactStatus
from harness.core.ports import ArtifactRepository, ArtifactStore, RunRepository


class ArtifactService:
    def __init__(
        self,
        *,
        runs: RunRepository,
        repository: ArtifactRepository,
        store: ArtifactStore,
        id_generator: IdGenerator,
    ) -> None:
        self._runs = runs
        self._repository = repository
        self._store = store
        self._id_generator = id_generator

    async def upload(
        self,
        *,
        tenant_id: str,
        run_id: str,
        name: str,
        media_type: str,
        content: bytes,
    ) -> Artifact:
        await self._runs.get(tenant_id, run_id)
        artifact_id = self._id_generator("artifact")
        pending = Artifact(
            artifact_id=artifact_id,
            run_id=run_id,
            tenant_id=tenant_id,
            name=name,
            media_type=media_type,
            status=ArtifactStatus.PENDING,
            object_key=f".pending/{tenant_id}/{artifact_id}",
        )
        await self._repository.add(pending)
        try:
            stored = await self._store.put(tenant_id, artifact_id, content)
        except Exception:
            await self._repository.update(
                pending.model_copy(update={"status": ArtifactStatus.FAILED})
            )
            raise
        ready = pending.model_copy(
            update={
                "status": ArtifactStatus.READY,
                "object_key": stored.object_key,
                "sha256": stored.sha256,
                "size_bytes": stored.size_bytes,
            }
        )
        await self._repository.update(ready)
        return ready

    async def list_for_run(self, tenant_id: str, run_id: str) -> list[Artifact]:
        await self._runs.get(tenant_id, run_id)
        return await self._repository.list_for_run(tenant_id, run_id)

    async def download(self, tenant_id: str, artifact_id: str) -> tuple[Artifact, bytes]:
        artifact = await self._repository.get(tenant_id, artifact_id)
        content = await self._store.get(tenant_id, artifact_id)
        return artifact, content
