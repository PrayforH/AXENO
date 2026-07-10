"""Agent validation and publication use cases."""

from pathlib import Path
from typing import Literal

from harness.application.types import Clock
from harness.core.manifest import AgentManifestSnapshot, load_manifest
from harness.core.models import AgentVersion, AgentVersionStatus
from harness.core.ports import AgentRegistry


class AgentService:
    def __init__(self, registry: AgentRegistry, *, clock: Clock) -> None:
        self._registry = registry
        self._clock = clock

    def validate(
        self,
        path: str | Path,
        *,
        environment: Literal["local", "test", "production"] = "local",
    ) -> AgentManifestSnapshot:
        return load_manifest(path, environment=environment)

    async def publish(
        self,
        tenant_id: str,
        path: str | Path,
        *,
        environment: Literal["local", "test", "production"] = "local",
    ) -> AgentVersion:
        snapshot = self.validate(path, environment=environment)
        manifest = snapshot.manifest
        version = AgentVersion(
            tenant_id=tenant_id,
            name=manifest.metadata.name,
            version=manifest.metadata.version,
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=self._clock(),
        )
        await self._registry.add(version)
        return version

