"""Stage immutable main and subagent runtime assets from the registry."""

from pathlib import Path

from harness.core.errors import ConflictError
from harness.core.manifest import (
    AgentManifestSnapshot,
    ManifestValidationError,
    materialize_python_tool_snapshot_set,
    materialize_skill_snapshot_set,
)
from harness.core.models import AgentVersion, AgentVersionStatus
from harness.core.ports import AgentRegistry


async def resolve_published_agent_versions(
    registry: AgentRegistry,
    *,
    tenant_id: str,
    owner_user_id: str,
    agent_name: str,
    agent_version: str,
) -> tuple[AgentVersion, dict[str, AgentVersion]]:
    """Resolve a fixed one-level SDK delegation graph and enforce publication state."""
    root = await registry.get(tenant_id, owner_user_id, agent_name, agent_version)
    if root.status is not AgentVersionStatus.PUBLISHED:
        raise ConflictError("sessions can only use a published Agent version")
    snapshot = AgentManifestSnapshot.model_validate(root.snapshot)
    children: dict[str, AgentVersion] = {}
    for subagent in snapshot.manifest.spec.subagents:
        name, separator, version_id = subagent.ref.rpartition("@")
        if not separator or not name or not version_id:
            raise ManifestValidationError(
                f"subagent reference requires name@version: {subagent.ref}"
            )
        runtime_name = subagent.runtime_name
        if runtime_name in children:
            raise ManifestValidationError(f"duplicate subagent runtime name: {runtime_name}")
        child = await registry.get(tenant_id, owner_user_id, name, version_id)
        if child.status is not AgentVersionStatus.PUBLISHED:
            raise ConflictError(f"subagent must be published before use: {name}@{version_id}")
        child_snapshot = AgentManifestSnapshot.model_validate(child.snapshot)
        if child_snapshot.manifest.spec.subagents:
            raise ManifestValidationError(
                f"nested subagent delegation is not supported: {runtime_name}"
            )
        children[runtime_name] = child
    return root, children


async def stage_published_agent_assets(
    registry: AgentRegistry,
    *,
    tenant_id: str,
    owner_user_id: str,
    agent_name: str,
    agent_version: str,
    workspace: Path,
) -> tuple[str, ...]:
    version, children = await resolve_published_agent_versions(
        registry,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        agent_name=agent_name,
        agent_version=agent_version,
    )
    snapshot = AgentManifestSnapshot.model_validate(version.snapshot)
    snapshots = [snapshot]
    for child in children.values():
        snapshots.append(AgentManifestSnapshot.model_validate(child.snapshot))
    materialize_python_tool_snapshot_set(snapshots, workspace)
    return materialize_skill_snapshot_set(snapshots, workspace)
