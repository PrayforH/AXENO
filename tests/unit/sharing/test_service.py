from datetime import UTC, datetime

import pytest

from harness.adapters.memory import InMemoryAgentRegistry
from harness.core.errors import NotFoundError, PermissionDeniedError
from harness.core.models import AgentVersion, AgentVersionStatus
from harness.sharing.models import SpaceRole
from harness.sharing.repositories import InMemoryTeamSpaceRepository
from harness.sharing.service import TeamSpaceService


def agent(owner: str) -> AgentVersion:
    return AgentVersion(
        tenant_id="tenant-a",
        owner_user_id=owner,
        name="research-agent",
        version="1.0.0",
        status=AgentVersionStatus.PUBLISHED,
        manifest_hash="hash-a",
        snapshot={"manifest": {"metadata": {"name": "research-agent"}}},
        created_at=datetime(2026, 8, 3, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_space_shares_agent_without_copying_and_fork_is_personal() -> None:
    registry = InMemoryAgentRegistry()
    await registry.add(agent("alice"))
    service = TeamSpaceService(
        InMemoryTeamSpaceRepository(),
        registry,
        clock=lambda: datetime(2026, 8, 3, tzinfo=UTC),
        id_generator=lambda _prefix: "space-one",
    )
    space = await service.create("tenant-a", "alice", "调查组")
    await service.put_member(
        "tenant-a", "alice", space.space_id, "bob", SpaceRole.VIEWER
    )
    await service.share_agent(
        "tenant-a",
        "alice",
        space.space_id,
        "alice",
        "research-agent",
        "1.0.0",
    )

    accessible = await service.list_accessible_agents("tenant-a", "bob")
    assert [(item[0].space_id, item[3].owner_user_id) for item in accessible] == [
        ("space-one", "alice")
    ]
    fork = await service.fork_agent(
        "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
    )
    assert fork.owner_user_id == "bob"
    assert fork.manifest_hash == "hash-a"
    original = await registry.get(
        "tenant-a", "alice", "research-agent", "1.0.0"
    )
    assert original.owner_user_id == "alice"


@pytest.mark.asyncio
async def test_viewer_run_policy_and_membership_revocation_fail_closed() -> None:
    registry = InMemoryAgentRegistry()
    await registry.add(agent("alice"))
    service = TeamSpaceService(
        InMemoryTeamSpaceRepository(), registry, id_generator=lambda _prefix: "space-one"
    )
    space = await service.create("tenant-a", "alice", "调查组")
    await service.put_member(
        "tenant-a", "alice", space.space_id, "bob", SpaceRole.VIEWER
    )
    await service.share_agent(
        "tenant-a",
        "alice",
        space.space_id,
        "alice",
        "research-agent",
        "1.0.0",
        runnable_by_viewer=False,
    )

    with pytest.raises(PermissionDeniedError):
        await service.require_agent_access(
            "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
        )
    await service.remove_member("tenant-a", "alice", space.space_id, "bob")
    with pytest.raises(NotFoundError):
        await service.require_agent_access(
            "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
        )


@pytest.mark.asyncio
async def test_contributor_cannot_share_another_users_agent() -> None:
    registry = InMemoryAgentRegistry()
    await registry.add(agent("alice"))
    service = TeamSpaceService(
        InMemoryTeamSpaceRepository(), registry, id_generator=lambda _prefix: "space-one"
    )
    space = await service.create("tenant-a", "alice", "调查组")
    await service.put_member(
        "tenant-a", "alice", space.space_id, "bob", SpaceRole.CONTRIBUTOR
    )
    with pytest.raises(PermissionDeniedError):
        await service.share_agent(
            "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
        )
