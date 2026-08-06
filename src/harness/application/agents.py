"""Agent validation and publication use cases."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from harness.agent_package import (
    AgentBundleValidationError,
    check_agent_package,
    extract_agent_bundle,
)
from harness.application.types import Clock
from harness.core.errors import ConflictError
from harness.core.manifest import AgentManifestSnapshot, load_manifest
from harness.core.models import AgentVersion, AgentVersionStatus
from harness.core.ports import AgentRegistry


class AgentService:
    def __init__(
        self,
        registry: AgentRegistry,
        *,
        clock: Clock,
        environment: Literal["local", "test", "production"] = "local",
        allow_path_publication: bool | None = None,
        default_manifest_path: str | Path | None = None,
    ) -> None:
        self._registry = registry
        self._clock = clock
        self._environment: Literal["local", "test", "production"] = environment
        self.path_publication_enabled = (
            environment != "production"
            if allow_path_publication is None
            else allow_path_publication
        )
        self._default_manifest_path = (
            Path(default_manifest_path) if default_manifest_path is not None else None
        )

    def validate(
        self,
        path: str | Path,
        *,
        environment: Literal["local", "test", "production"] | None = None,
    ) -> AgentManifestSnapshot:
        active_environment: Literal["local", "test", "production"] = (
            environment or self._environment
        )
        if active_environment == "production":
            return check_agent_package(path, environment=active_environment).snapshot
        return load_manifest(path, environment=active_environment)

    async def list_published(self, tenant_id: str, owner_user_id: str) -> list[AgentVersion]:
        return [
            version
            for version in await self._registry.list_for_user(tenant_id, owner_user_id)
            if version.status is AgentVersionStatus.PUBLISHED
        ]

    async def ensure_user_default(
        self, tenant_id: str, owner_user_id: str
    ) -> AgentVersion | None:
        """Idempotently provision the platform default into a user's private catalog."""

        if self._default_manifest_path is None:
            return None
        report = check_agent_package(
            self._default_manifest_path, environment="production"
        )
        snapshot = report.snapshot
        name = snapshot.manifest.metadata.name
        version = snapshot.manifest.metadata.version
        for existing in await self._registry.list_for_user(tenant_id, owner_user_id):
            if (
                existing.name == name
                and existing.version == version
                and existing.status is AgentVersionStatus.PUBLISHED
            ):
                return existing
        return await self._publish_snapshot(
            tenant_id,
            owner_user_id,
            snapshot,
            package_hash=report.package_hash,
        )

    async def publish(
        self,
        tenant_id: str,
        owner_user_id: str,
        path: str | Path,
        *,
        environment: Literal["local", "test", "production"] | None = None,
    ) -> AgentVersion:
        snapshot = self.validate(path, environment=environment)
        return await self._publish_snapshot(tenant_id, owner_user_id, snapshot)

    async def publish_bundle(
        self, tenant_id: str, owner_user_id: str, content: bytes
    ) -> AgentVersion:
        with TemporaryDirectory(prefix="harness-agent-bundle-") as directory:
            manifest, claimed_hash, claimed_package_hash = extract_agent_bundle(
                content, destination=directory
            )
            report = check_agent_package(manifest, environment="production")
            snapshot = report.snapshot
            if snapshot.content_hash != claimed_hash:
                raise AgentBundleValidationError(
                    "Agent bundle provenance does not match its immutable snapshot"
                )
            if report.package_hash != claimed_package_hash:
                raise AgentBundleValidationError(
                    "Agent bundle provenance does not match its release package"
                )
            return await self._publish_snapshot(
                tenant_id,
                owner_user_id,
                snapshot,
                package_hash=report.package_hash,
            )

    async def _publish_snapshot(
        self,
        tenant_id: str,
        owner_user_id: str,
        snapshot: AgentManifestSnapshot,
        *,
        package_hash: str | None = None,
    ) -> AgentVersion:
        manifest = snapshot.manifest
        version = AgentVersion(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            name=manifest.metadata.name,
            version=manifest.metadata.version,
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            package_hash=package_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=self._clock(),
        )
        try:
            await self._registry.add(version)
        except ConflictError:
            existing = await self._registry.get(
                tenant_id,
                owner_user_id,
                manifest.metadata.name,
                manifest.metadata.version,
            )
            if existing.manifest_hash != version.manifest_hash or (
                package_hash is not None and existing.package_hash != package_hash
            ):
                raise
            return existing
        return version
