from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.adapters.memory import InMemoryAgentRegistry
from harness.application.agent_assets import stage_published_agent_assets
from harness.core.manifest import load_manifest
from harness.core.models import AgentVersion, AgentVersionStatus


async def _publish(registry: InMemoryAgentRegistry, manifest_path: str) -> None:
    snapshot = load_manifest(manifest_path)
    metadata = snapshot.manifest.metadata
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name=metadata.name,
            version=metadata.version,
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )


@pytest.mark.asyncio
async def test_stages_main_and_pinned_subagent_skills(tmp_path: Path) -> None:
    registry = InMemoryAgentRegistry()
    await _publish(registry, "agents/helper-agent/agent.yaml")
    await _publish(registry, "agents/echo-agent/agent.yaml")

    names = await stage_published_agent_assets(
        registry,
        tenant_id="tenant-a",
        agent_name="echo-agent",
        agent_version="0.4.0",
        workspace=tmp_path,
    )

    assert names == ("delegated-investigation", "workspace-validation")
    assert (
        tmp_path / ".claude/skills/delegated-investigation/SKILL.md"
    ).is_file()
    assert (tmp_path / ".claude/skills/workspace-validation/SKILL.md").is_file()
