from datetime import UTC, datetime

import pytest

from harness.adapters.memory import InMemoryAgentRegistry
from harness.core.errors import NotFoundError, PermissionDeniedError
from harness.core.models import AgentVersion, AgentVersionStatus
from harness.sharing.models import (
    AgentPermission,
    AgentScope,
    GranteeType,
    SpaceRole,
)
from harness.sharing.repositories import InMemoryTeamSpaceRepository
from harness.sharing.service import TeamSpaceService
from harness.sharing.workspace_repositories import InMemoryWorkspaceAgentRepository


def agent(owner: str, version: str = "1.0.0", name: str = "research-agent") -> AgentVersion:
    return AgentVersion(
        tenant_id="tenant-a",
        owner_user_id=owner,
        name=name,
        version=version,
        status=AgentVersionStatus.PUBLISHED,
        manifest_hash=f"hash-{owner}-{version}",
        snapshot={"manifest": {"metadata": {"name": name}}},
        created_at=datetime(2026, 8, 3, tzinfo=UTC),
    )


def service() -> tuple[TeamSpaceService, InMemoryAgentRegistry, InMemoryWorkspaceAgentRepository]:
    registry = InMemoryAgentRegistry()
    workspace = InMemoryWorkspaceAgentRepository()
    team = TeamSpaceService(
        InMemoryTeamSpaceRepository(),
        workspace,
        registry,
        clock=lambda: datetime(2026, 8, 3, tzinfo=UTC),
        id_generator=lambda _prefix: "space-one",
    )
    return team, registry, workspace


@pytest.mark.asyncio
async def test_sharing_creates_workspace_agent_with_release_and_current_version() -> None:
    team, registry, workspace = service()
    await registry.add(agent("alice"))
    space = await team.create("tenant-a", "alice", "调查组")
    await team.put_member(
        "tenant-a", "alice", space.space_id, "bob", SpaceRole.VIEWER
    )
    shared_agent, release = await team.share_agent(
        "tenant-a",
        "alice",
        space.space_id,
        "alice",
        "research-agent",
        "1.0.0",
    )

    assert shared_agent.scope is AgentScope.WORKSPACE
    assert shared_agent.space_id == space.space_id
    assert shared_agent.current_version == "1.0.0"
    assert release.agent_id == shared_agent.agent_id
    assert release.source_owner_user_id == "alice"
    assert release.version == "1.0.0"

    # Sharing another version reuses the same stable identity.
    await registry.add(agent("alice", version="1.1.0"))
    shared_again, release_two = await team.share_agent(
        "tenant-a",
        "alice",
        space.space_id,
        "alice",
        "research-agent",
        "1.1.0",
        runnable_by_viewer=False,
    )
    assert shared_again.agent_id == shared_agent.agent_id
    assert release_two.version == "1.1.0"
    # The newest Release becomes the current published version.
    assert shared_again.current_version == "1.1.0"

    # The catalog shows one entry per workspace Agent with its current Release.
    accessible = await team.list_accessible_agents("tenant-a", "bob")
    assert [(item[0].space_id, item[2].agent_id, item[3].version) for item in accessible] == [
        ("space-one", shared_agent.agent_id, "1.1.0")
    ]
    assert accessible[0][4].manifest_hash == "hash-alice-1.1.0"

    # Runtime access gate resolves coordinates through Releases.
    release_row = await team.require_agent_access(
        "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
    )
    assert release_row.version == "1.0.0"


@pytest.mark.asyncio
async def test_promote_switches_current_version_without_changing_identity() -> None:
    team, registry, workspace = service()
    await registry.add(agent("alice", version="1.0.0"))
    await registry.add(agent("alice", version="1.1.0"))
    space = await team.create("tenant-a", "alice", "调查组")
    await team.put_member(
        "tenant-a", "alice", space.space_id, "bob", SpaceRole.CONTRIBUTOR
    )
    shared_agent, _ = await team.share_agent(
        "tenant-a", "alice", space.space_id, "alice", "research-agent", "1.0.0"
    )
    await team.share_agent(
        "tenant-a", "alice", space.space_id, "alice", "research-agent", "1.1.0"
    )
    # The most recently shared Release becomes the current version.
    stored = await workspace.get_agent("tenant-a", shared_agent.agent_id)
    assert stored.current_version == "1.1.0"

    # Contributors can promote their own Releases; viewers cannot promote.
    with pytest.raises(PermissionDeniedError):
        await team.promote_release(
            "tenant-a", "bob", space.space_id, shared_agent.agent_id, "1.0.0"
        )
    await team.promote_release(
        "tenant-a", "alice", space.space_id, shared_agent.agent_id, "1.0.0"
    )
    stored = await workspace.get_agent("tenant-a", shared_agent.agent_id)
    assert stored.agent_id == shared_agent.agent_id
    assert stored.current_version == "1.0.0"


@pytest.mark.asyncio
async def test_unsharing_last_release_clears_current_version() -> None:
    team, registry, workspace = service()
    await registry.add(agent("alice"))
    space = await team.create("tenant-a", "alice", "调查组")
    shared_agent, _ = await team.share_agent(
        "tenant-a", "alice", space.space_id, "alice", "research-agent", "1.0.0"
    )
    await team.unshare_agent(
        "tenant-a", "alice", space.space_id, shared_agent.agent_id, "1.0.0"
    )
    stored = await workspace.get_agent("tenant-a", shared_agent.agent_id)
    assert stored.current_version is None
    assert await team.list_releases(
        "tenant-a", "alice", space.space_id, shared_agent.agent_id
    ) == []


@pytest.mark.asyncio
async def test_viewer_run_policy_and_membership_revocation_fail_closed() -> None:
    team, registry, workspace = service()
    await registry.add(agent("alice"))
    space = await team.create("tenant-a", "alice", "调查组")
    await team.put_member(
        "tenant-a", "alice", space.space_id, "bob", SpaceRole.VIEWER
    )
    shared_agent, _ = await team.share_agent(
        "tenant-a",
        "alice",
        space.space_id,
        "alice",
        "research-agent",
        "1.0.0",
        runnable_by_viewer=False,
    )

    with pytest.raises(PermissionDeniedError):
        await team.require_agent_access(
            "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
        )
    await team.remove_member("tenant-a", "alice", space.space_id, "bob")
    with pytest.raises(NotFoundError):
        await team.require_agent_access(
            "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
        )


@pytest.mark.asyncio
async def test_acl_can_grant_chat_to_a_viewer() -> None:
    team, registry, workspace = service()
    await registry.add(agent("alice"))
    space = await team.create("tenant-a", "alice", "调查组")
    await team.put_member(
        "tenant-a", "alice", space.space_id, "bob", SpaceRole.VIEWER
    )
    shared_agent, _ = await team.share_agent(
        "tenant-a",
        "alice",
        space.space_id,
        "alice",
        "research-agent",
        "1.0.0",
        runnable_by_viewer=False,
    )
    with pytest.raises(PermissionDeniedError):
        await team.require_agent_access(
            "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
        )

    # Only managers can grant ACL rows.
    with pytest.raises(PermissionDeniedError):
        await team.put_acl(
            "tenant-a",
            "bob",
            space.space_id,
            shared_agent.agent_id,
            GranteeType.USER,
            "bob",
            AgentPermission.CHAT,
        )
    await team.put_acl(
        "tenant-a",
        "alice",
        space.space_id,
        shared_agent.agent_id,
        GranteeType.USER,
        "bob",
        AgentPermission.CHAT,
    )
    release = await team.require_agent_access(
        "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
    )
    assert release.version == "1.0.0"

    permissions = await team.effective_permissions(
        "tenant-a", "bob", space.space_id, shared_agent.agent_id
    )
    assert AgentPermission.CHAT in permissions

    await team.delete_acl(
        "tenant-a",
        "alice",
        space.space_id,
        shared_agent.agent_id,
        GranteeType.USER,
        "bob",
        AgentPermission.CHAT,
    )
    with pytest.raises(PermissionDeniedError):
        await team.require_agent_access(
            "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
        )


@pytest.mark.asyncio
async def test_acl_grants_must_reference_space_members() -> None:
    team, registry, workspace = service()
    await registry.add(agent("alice"))
    space = await team.create("tenant-a", "alice", "调查组")
    shared_agent, _ = await team.share_agent(
        "tenant-a", "alice", space.space_id, "alice", "research-agent", "1.0.0"
    )
    with pytest.raises(NotFoundError):
        await team.put_acl(
            "tenant-a",
            "alice",
            space.space_id,
            shared_agent.agent_id,
            GranteeType.USER,
            "outsider",
            AgentPermission.CHAT,
        )


@pytest.mark.asyncio
async def test_fork_copies_current_release_to_personal_scope() -> None:
    team, registry, workspace = service()
    await registry.add(agent("alice", version="1.0.0"))
    await registry.add(agent("alice", version="1.1.0"))
    space = await team.create("tenant-a", "alice", "调查组")
    await team.put_member(
        "tenant-a", "alice", space.space_id, "bob", SpaceRole.CONTRIBUTOR
    )
    shared_agent, _ = await team.share_agent(
        "tenant-a", "alice", space.space_id, "alice", "research-agent", "1.0.0"
    )
    await team.share_agent(
        "tenant-a", "alice", space.space_id, "alice", "research-agent", "1.1.0"
    )
    # Fork resolves the current Release (1.1.0) of the workspace Agent.
    fork = await team.fork_agent("tenant-a", "bob", space.space_id, shared_agent.agent_id)
    assert fork.owner_user_id == "bob"
    assert fork.version == "1.1.0"
    assert fork.manifest_hash == "hash-alice-1.1.0"
    original = await registry.get(
        "tenant-a", "alice", "research-agent", "1.1.0"
    )
    assert original.owner_user_id == "alice"


@pytest.mark.asyncio
async def test_contributor_cannot_share_another_users_agent() -> None:
    team, registry, workspace = service()
    await registry.add(agent("alice"))
    space = await team.create("tenant-a", "alice", "调查组")
    await team.put_member(
        "tenant-a", "alice", space.space_id, "bob", SpaceRole.CONTRIBUTOR
    )
    with pytest.raises(PermissionDeniedError):
        await team.share_agent(
            "tenant-a", "bob", space.space_id, "alice", "research-agent", "1.0.0"
        )
