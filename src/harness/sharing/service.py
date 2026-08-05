"""Team-space RBAC, workspace Agent identities, Releases and ACLs."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from harness.application.types import Clock, IdGenerator
from harness.auth.audit import AuditService
from harness.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from harness.core.models import AgentVersion, AgentVersionStatus
from harness.core.ports import AgentRegistry
from harness.sharing.models import (
    AgentAcl,
    AgentPermission,
    AgentRelease,
    AgentScope,
    ConnectionMode,
    GranteeType,
    GroupMember,
    SharedKnowledgeBase,
    SpaceRole,
    TeamSpace,
    TeamSpaceMember,
    UserGroup,
    WorkspaceAgent,
    WorkspaceAgentStatus,
)
from harness.sharing.repositories import TeamSpaceRepository
from harness.sharing.workspace_repositories import WorkspaceAgentRepository
from harness.studio.repositories import AgentDraftRepository

_MANAGE_ROLES = frozenset({SpaceRole.OWNER, SpaceRole.ADMIN})
_PUBLISH_ROLES = frozenset({SpaceRole.OWNER, SpaceRole.ADMIN, SpaceRole.CONTRIBUTOR})

# Baseline permissions derived from the space role of the requesting member.
# VIEWER intentionally lacks CHAT: chatting is granted per Release via
# runnable_by_viewer or via an explicit ACL row.
_ROLE_PERMISSIONS: dict[SpaceRole, frozenset[AgentPermission]] = {
    SpaceRole.OWNER: frozenset(
        {
            AgentPermission.VIEW,
            AgentPermission.CHAT,
            AgentPermission.EDIT,
            AgentPermission.PUBLISH,
            AgentPermission.MANAGE,
        }
    ),
    SpaceRole.ADMIN: frozenset(
        {
            AgentPermission.VIEW,
            AgentPermission.CHAT,
            AgentPermission.EDIT,
            AgentPermission.PUBLISH,
            AgentPermission.MANAGE,
        }
    ),
    SpaceRole.CONTRIBUTOR: frozenset(
        {
            AgentPermission.VIEW,
            AgentPermission.CHAT,
            AgentPermission.EDIT,
            AgentPermission.PUBLISH,
        }
    ),
    SpaceRole.VIEWER: frozenset({AgentPermission.VIEW}),
}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class TeamSpaceService:
    def __init__(
        self,
        repository: TeamSpaceRepository,
        workspace_agents: WorkspaceAgentRepository,
        agents: AgentRegistry,
        *,
        drafts: AgentDraftRepository | None = None,
        audit: AuditService | None = None,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self.repository = repository
        self._workspace_agents = workspace_agents
        self._agents = agents
        self._drafts = drafts
        self._audit = audit
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._ids: IdGenerator = id_generator or _id

    async def _record_audit(
        self,
        *,
        tenant_id: str,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, object],
    ) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.record(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome="success",
                details=details,
            )
        except Exception:
            # Audit failure must never break the authorization flow itself.
            pass

    # ------------------------------------------------------------------
    # Spaces and members
    # ------------------------------------------------------------------

    async def create(
        self, tenant_id: str, actor_id: str, name: str, description: str = ""
    ) -> TeamSpace:
        now = self._clock()
        space = TeamSpace(
            tenantId=tenant_id,
            spaceId=self._ids("space"),
            name=name.strip(),
            description=description.strip(),
            createdBy=actor_id,
            createdAt=now,
        )
        if not space.name:
            raise ConflictError("team space name must not be empty")
        owner = TeamSpaceMember(
            tenantId=tenant_id,
            spaceId=space.space_id,
            userId=actor_id,
            role=SpaceRole.OWNER,
            createdAt=now,
        )
        await self.repository.add_space(space, owner)
        return space

    async def list_for_user(self, tenant_id: str, user_id: str) -> list[TeamSpace]:
        return await self.repository.list_spaces_for_user(tenant_id, user_id)

    async def get_for_user(
        self, tenant_id: str, user_id: str, space_id: str
    ) -> tuple[TeamSpace, TeamSpaceMember]:
        member = await self._require_member(tenant_id, space_id, user_id)
        return await self.repository.get_space(tenant_id, space_id), member

    async def list_members(
        self, tenant_id: str, actor_id: str, space_id: str
    ) -> list[TeamSpaceMember]:
        await self._require_member(tenant_id, space_id, actor_id)
        return await self.repository.list_members(tenant_id, space_id)

    async def require_manage(self, tenant_id: str, actor_id: str, space_id: str) -> None:
        await self._require_role(tenant_id, space_id, actor_id, _MANAGE_ROLES)

    async def put_member(
        self,
        tenant_id: str,
        actor_id: str,
        space_id: str,
        user_id: str,
        role: SpaceRole,
    ) -> TeamSpaceMember:
        actor = await self._require_role(tenant_id, space_id, actor_id, _MANAGE_ROLES)
        current = await self.repository.get_member(tenant_id, space_id, user_id)
        if actor.role is SpaceRole.ADMIN and (
            role in _MANAGE_ROLES or (current is not None and current.role in _MANAGE_ROLES)
        ):
            raise PermissionDeniedError("space admins cannot manage owners or other admins")
        if current is not None and current.role is SpaceRole.OWNER and role is not SpaceRole.OWNER:
            members = await self.repository.list_members(tenant_id, space_id)
            if sum(item.role is SpaceRole.OWNER for item in members) == 1:
                raise ConflictError("team space must retain at least one owner")
        member = TeamSpaceMember(
            tenantId=tenant_id,
            spaceId=space_id,
            userId=user_id,
            role=role,
            createdAt=current.created_at if current is not None else self._clock(),
        )
        await self.repository.put_member(member)
        return member

    async def remove_member(
        self, tenant_id: str, actor_id: str, space_id: str, user_id: str
    ) -> None:
        actor = await self._require_member(tenant_id, space_id, actor_id)
        target = await self._require_member(tenant_id, space_id, user_id)
        if actor_id != user_id and actor.role not in _MANAGE_ROLES:
            raise PermissionDeniedError("only space managers can remove another member")
        if actor.role is SpaceRole.ADMIN and target.role in _MANAGE_ROLES:
            raise PermissionDeniedError("space admins cannot remove owners or other admins")
        if target.role is SpaceRole.OWNER:
            members = await self.repository.list_members(tenant_id, space_id)
            if sum(item.role is SpaceRole.OWNER for item in members) == 1:
                raise ConflictError("team space must retain at least one owner")
        await self.repository.delete_member(tenant_id, space_id, user_id)

    # ------------------------------------------------------------------
    # Workspace Agents and Releases
    # ------------------------------------------------------------------

    async def share_agent(
        self,
        tenant_id: str,
        actor_id: str,
        space_id: str,
        owner_user_id: str,
        name: str,
        version: str,
        *,
        runnable_by_viewer: bool = True,
        connection_mode: ConnectionMode = ConnectionMode.CALLER_OWNED,
    ) -> tuple[WorkspaceAgent, AgentRelease]:
        """Release an immutable personal version as a workspace Agent Release.

        The workspace Agent identity is stable: sharing more versions of the
        same name reuses the existing agent and only appends Releases.
        """
        await self._require_role(tenant_id, space_id, actor_id, _PUBLISH_ROLES)
        if owner_user_id != actor_id:
            raise PermissionDeniedError("users can only share their own Agents")
        agent_version = await self._agents.get(tenant_id, owner_user_id, name, version)
        if agent_version.status is not AgentVersionStatus.PUBLISHED:
            raise ConflictError("only published Agent versions can be shared")
        now = self._clock()
        agent = await self._workspace_agents.get_workspace_agent(
            tenant_id, space_id, name
        )
        if agent is None:
            agent = WorkspaceAgent(
                tenantId=tenant_id,
                agentId=self._ids("agent"),
                scope=AgentScope.WORKSPACE,
                spaceId=space_id,
                name=name,
                displayName=agent_version.snapshot.get("display_name", name),
                createdBy=actor_id,
                createdAt=now,
                updatedAt=now,
            )
            await self._workspace_agents.add_agent(agent)
        release = AgentRelease(
            tenantId=tenant_id,
            spaceId=space_id,
            agentId=agent.agent_id,
            version=version,
            sourceOwnerUserId=owner_user_id,
            sourceName=name,
            promotedBy=actor_id,
            runnableByViewer=runnable_by_viewer,
            connectionMode=connection_mode,
            createdAt=now,
        )
        try:
            await self._workspace_agents.add_release(release)
        except ConflictError:
            existing = await self._workspace_agents.get_release(
                tenant_id, space_id, agent.agent_id, version
            )
            if existing.runnable_by_viewer != runnable_by_viewer:
                raise ConflictError(
                    f"agent release already shared with different settings: "
                    f"{name}@{version}"
                ) from None
            return agent, existing
        if agent.current_version is None:
            agent = await self._promote_locked(tenant_id, agent, version, actor_id)
        else:
            current = await self._workspace_agents.get_release(
                tenant_id, space_id, agent.agent_id, agent.current_version
            )
            # The most recently shared Release becomes the current version.
            if release.created_at >= current.created_at:
                agent = await self._promote_locked(tenant_id, agent, version, actor_id)
        await self._record_audit(
            tenant_id=tenant_id,
            user_id=actor_id,
            action="agent.share",
            resource_type="agent_release",
            resource_id=f"{agent.agent_id}@{version}",
            details={
                "agent_id": agent.agent_id,
                "space_id": space_id,
                "name": name,
                "version": version,
                "runnable_by_viewer": runnable_by_viewer,
                "connection_mode": connection_mode.value,
            },
        )
        return agent, release

    async def unshare_agent(
        self,
        tenant_id: str,
        actor_id: str,
        space_id: str,
        agent_id: str,
        version: str,
    ) -> None:
        member = await self._require_role(tenant_id, space_id, actor_id, _PUBLISH_ROLES)
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.space_id != space_id:
            raise NotFoundError(f"workspace agent not found: {agent_id}")
        if (
            member.role is SpaceRole.CONTRIBUTOR
            and agent.created_by != actor_id
            and not await self._effective(
                tenant_id, member, agent, AgentPermission.MANAGE
            )
        ):
            raise PermissionDeniedError(
                "contributors can only unshare Agents they created or manage"
            )
        deleted = await self._workspace_agents.delete_release(
            tenant_id, space_id, agent_id, version
        )
        if not deleted:
            raise NotFoundError(f"agent release not found: {agent_id}@{version}")
        remaining = await self._workspace_agents.list_releases(
            tenant_id, space_id, agent_id
        )
        if not remaining:
            await self._workspace_agents.update_agent(
                agent.model_copy(update={"current_version": None, "updated_at": self._clock()})
            )
        elif agent.current_version == version:
            latest = max(remaining, key=lambda item: item.created_at)
            await self._promote_locked(tenant_id, agent, latest.version, actor_id)

    async def promote_release(
        self,
        tenant_id: str,
        actor_id: str,
        space_id: str,
        agent_id: str,
        version: str,
    ) -> WorkspaceAgent:
        """Switch the current published version without changing Agent identity."""
        member = await self._require_role(tenant_id, space_id, actor_id, _PUBLISH_ROLES)
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.space_id != space_id:
            raise NotFoundError(f"workspace agent not found: {agent_id}")
        if not await self._effective(tenant_id, member, agent, AgentPermission.PUBLISH):
            raise PermissionDeniedError("space role does not allow publishing this Agent")
        release = await self._workspace_agents.get_release(
            tenant_id, space_id, agent_id, version
        )
        if release.source_owner_user_id != actor_id and member.role is SpaceRole.CONTRIBUTOR:
            raise PermissionDeniedError(
                "contributors can only promote their own Agent releases"
            )
        promoted = await self._promote_locked(tenant_id, agent, version, actor_id)
        await self._record_audit(
            tenant_id=tenant_id,
            user_id=actor_id,
            action="agent.promote",
            resource_type="workspace_agent",
            resource_id=agent.agent_id,
            details={
                "space_id": space_id,
                "name": agent.name,
                "version": version,
                "previous_version": agent.current_version,
            },
        )
        return promoted

    async def _promote_locked(
        self, tenant_id: str, agent: WorkspaceAgent, version: str, actor_id: str
    ) -> WorkspaceAgent:
        updated = agent.model_copy(
            update={
                "current_version": version,
                "updated_at": self._clock(),
            }
        )
        await self._workspace_agents.update_agent(updated)
        return updated

    async def list_agents(
        self, tenant_id: str, user_id: str, space_id: str
    ) -> list[WorkspaceAgent]:
        """Workspace Agents visible to a member (each carries current_version)."""
        await self._require_member(tenant_id, space_id, user_id)
        agents = await self._workspace_agents.list_agents_for_space(tenant_id, space_id)
        return [agent for agent in agents if agent.status is WorkspaceAgentStatus.ACTIVE]

    async def list_releases(
        self, tenant_id: str, user_id: str, space_id: str, agent_id: str
    ) -> list[tuple[AgentRelease, AgentVersion]]:
        """Release history of one workspace Agent, resolved to immutable versions."""
        await self._require_member(tenant_id, space_id, user_id)
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.space_id != space_id:
            raise NotFoundError(f"workspace agent not found: {agent_id}")
        result: list[tuple[AgentRelease, AgentVersion]] = []
        for release in await self._workspace_agents.list_releases(
            tenant_id, space_id, agent_id
        ):
            try:
                version = await self._agents.get(
                    tenant_id,
                    release.source_owner_user_id,
                    release.source_name,
                    release.version,
                )
            except NotFoundError:
                continue
            if version.status is AgentVersionStatus.PUBLISHED:
                result.append((release, version))
        return result

    async def list_accessible_agents(
        self, tenant_id: str, user_id: str
    ) -> list[tuple[TeamSpace, TeamSpaceMember, WorkspaceAgent, AgentRelease, AgentVersion]]:
        """One catalog entry per workspace Agent using its current Release."""
        result: list[
            tuple[TeamSpace, TeamSpaceMember, WorkspaceAgent, AgentRelease, AgentVersion]
        ] = []
        for space in await self.repository.list_spaces_for_user(tenant_id, user_id):
            member = await self._require_member(tenant_id, space.space_id, user_id)
            for agent in await self.list_agents(tenant_id, user_id, space.space_id):
                if agent.current_version is None:
                    continue
                release = await self._workspace_agents.get_release(
                    tenant_id, space.space_id, agent.agent_id, agent.current_version
                )
                try:
                    version = await self._agents.get(
                        tenant_id,
                        release.source_owner_user_id,
                        release.source_name,
                        release.version,
                    )
                except NotFoundError:
                    continue
                if version.status is not AgentVersionStatus.PUBLISHED:
                    continue
                result.append((space, member, agent, release, version))
        return result

    async def get_release_version(
        self,
        tenant_id: str,
        user_id: str,
        space_id: str,
        agent_id: str,
        version: str,
    ) -> tuple[AgentRelease, AgentVersion]:
        """Resolve one Release to its immutable AgentVersion."""
        await self._require_member(tenant_id, space_id, user_id)
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.space_id != space_id:
            raise NotFoundError(f"workspace agent not found: {agent_id}")
        release = await self._workspace_agents.get_release(
            tenant_id, space_id, agent_id, version
        )
        version_row = await self._agents.get(
            tenant_id,
            release.source_owner_user_id,
            release.source_name,
            release.version,
        )
        return release, version_row

    async def require_agent_access(
        self,
        tenant_id: str,
        user_id: str,
        space_id: str,
        owner_user_id: str,
        name: str,
        version: str,
    ) -> AgentRelease:
        """Runtime gate for sessions: resolve the coordinate to a Release and
        check the member can chat with it (ACL-aware)."""
        member = await self._require_member(tenant_id, space_id, user_id)
        release = await self._workspace_agents.get_release_by_source(
            tenant_id, space_id, owner_user_id, name, version
        )
        if release is None:
            raise NotFoundError(f"shared agent not found: {name}@{version}")
        agent = await self._workspace_agents.get_agent(tenant_id, release.agent_id)
        if agent.status is not WorkspaceAgentStatus.ACTIVE:
            raise PermissionDeniedError("this shared Agent is archived")
        if member.role is SpaceRole.VIEWER:
            # Viewers need either the Release-level runnable_by_viewer flag or
            # an explicit ACL chat grant.
            if not release.runnable_by_viewer and not await self._effective(
                tenant_id, member, agent, AgentPermission.CHAT
            ):
                raise PermissionDeniedError("viewers cannot run this shared Agent")
        return release

    # ------------------------------------------------------------------
    # Agent ACLs
    # ------------------------------------------------------------------

    async def list_acls(
        self, tenant_id: str, user_id: str, space_id: str, agent_id: str
    ) -> list[AgentAcl]:
        member = await self._require_member(tenant_id, space_id, user_id)
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.space_id != space_id:
            raise NotFoundError(f"workspace agent not found: {agent_id}")
        if not await self._effective(tenant_id, member, agent, AgentPermission.VIEW):
            raise PermissionDeniedError("space role does not allow viewing this Agent")
        return await self._workspace_agents.list_acls(tenant_id, agent_id)

    async def put_acl(
        self,
        tenant_id: str,
        actor_id: str,
        space_id: str,
        agent_id: str,
        grantee_type: GranteeType,
        grantee_id: str,
        permission: AgentPermission,
    ) -> AgentAcl:
        await self._require_role(tenant_id, space_id, actor_id, _MANAGE_ROLES)
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.space_id != space_id:
            raise NotFoundError(f"workspace agent not found: {agent_id}")
        if grantee_type is GranteeType.USER:
            grantee = await self.repository.get_member(tenant_id, space_id, grantee_id)
            if grantee is None:
                raise NotFoundError(
                    f"grantee is not a member of this space: {grantee_id}"
                )
        if grantee_type is GranteeType.GROUP:
            await self._workspace_agents.get_group(tenant_id, grantee_id)
        acl = AgentAcl(
            tenantId=tenant_id,
            agentId=agent_id,
            granteeType=grantee_type,
            granteeId=grantee_id,
            permission=permission,
            grantedBy=actor_id,
            createdAt=self._clock(),
        )
        try:
            await self._workspace_agents.add_acl(acl)
        except ConflictError:
            # ACL rows are idempotent: granting the same permission again is a no-op.
            return acl
        return acl

    async def delete_acl(
        self,
        tenant_id: str,
        actor_id: str,
        space_id: str,
        agent_id: str,
        grantee_type: GranteeType,
        grantee_id: str,
        permission: AgentPermission,
    ) -> None:
        await self._require_role(tenant_id, space_id, actor_id, _MANAGE_ROLES)
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.space_id != space_id:
            raise NotFoundError(f"workspace agent not found: {agent_id}")
        deleted = await self._workspace_agents.delete_acl(
            tenant_id, agent_id, grantee_type, grantee_id, permission
        )
        if not deleted:
            raise NotFoundError(
                f"agent ACL not found: {grantee_type.value}:{grantee_id} {permission.value}"
            )

    async def effective_permissions(
        self,
        tenant_id: str,
        user_id: str,
        space_id: str,
        agent_id: str,
    ) -> frozenset[AgentPermission]:
        member = await self._require_member(tenant_id, space_id, user_id)
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.space_id != space_id:
            raise NotFoundError(f"workspace agent not found: {agent_id}")
        baseline = _ROLE_PERMISSIONS[member.role]
        explicit = await self._explicit_permissions(
            tenant_id, member, agent_id
        )
        return frozenset(baseline.union(explicit))

    async def _effective(
        self,
        tenant_id: str,
        member: TeamSpaceMember,
        agent: WorkspaceAgent,
        permission: AgentPermission,
    ) -> bool:
        """Baseline role permission unioned with explicit ACL rows."""
        baseline = _ROLE_PERMISSIONS[member.role]
        if permission in baseline:
            return True
        return permission in await self._explicit_permissions(
            tenant_id, member, agent.agent_id
        )

    async def _explicit_permissions(
        self, tenant_id: str, member: TeamSpaceMember, agent_id: str
    ) -> set[AgentPermission]:
        """ACL rows granted to this user directly, via their space role, or
        via tenant user groups."""
        explicit: set[AgentPermission] = set()
        group_ids = await self._workspace_agents.list_groups_for_user(
            tenant_id, member.user_id
        )
        for acl in await self._workspace_agents.list_acls(tenant_id, agent_id):
            if acl.grantee_type is GranteeType.USER and acl.grantee_id == member.user_id:
                explicit.add(acl.permission)
            elif acl.grantee_type is GranteeType.SPACE_ROLE and acl.grantee_id == member.role.value:
                explicit.add(acl.permission)
            elif acl.grantee_type is GranteeType.GROUP and acl.grantee_id in group_ids:
                explicit.add(acl.permission)
        return explicit

    # ------------------------------------------------------------------
    # Forking
    # ------------------------------------------------------------------

    async def fork_agent(
        self,
        tenant_id: str,
        user_id: str,
        space_id: str,
        agent_id: str,
        version: str | None = None,
    ) -> AgentVersion:
        member = await self._require_member(tenant_id, space_id, user_id)
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.space_id != space_id:
            raise NotFoundError(f"workspace agent not found: {agent_id}")
        release = await self._workspace_agents.get_release(
            tenant_id, space_id, agent_id, version or (agent.current_version or "")
        )
        if member.role is SpaceRole.VIEWER and not release.runnable_by_viewer:
            raise PermissionDeniedError("viewers cannot run this shared Agent")
        source = await self._agents.get(
            tenant_id,
            release.source_owner_user_id,
            release.source_name,
            release.version,
        )
        fork = source.model_copy(update={"owner_user_id": user_id, "created_at": self._clock()})
        try:
            await self._agents.add(fork)
        except ConflictError:
            existing = await self._agents.get(tenant_id, user_id, source.name, source.version)
            if existing.manifest_hash != source.manifest_hash:
                raise ConflictError(
                    f"personal Agent already exists with different content: "
                    f"{source.name}@{source.version}"
                ) from None
            return existing
        return fork

    # ------------------------------------------------------------------
    # Knowledge grants
    # ------------------------------------------------------------------

    async def share_knowledge(
        self, tenant_id: str, actor_id: str, space_id: str, reference: str
    ) -> SharedKnowledgeBase:
        await self._require_role(tenant_id, space_id, actor_id, _MANAGE_ROLES)
        shared = SharedKnowledgeBase(
            tenantId=tenant_id,
            spaceId=space_id,
            knowledgeBaseReference=reference,
            sharedBy=actor_id,
            createdAt=self._clock(),
        )
        await self.repository.add_shared_knowledge(shared)
        return shared

    async def list_knowledge(
        self, tenant_id: str, user_id: str, space_id: str
    ) -> list[SharedKnowledgeBase]:
        await self._require_member(tenant_id, space_id, user_id)
        return await self.repository.list_shared_knowledge(tenant_id, space_id)

    async def unshare_knowledge(
        self, tenant_id: str, actor_id: str, space_id: str, reference: str
    ) -> None:
        await self._require_role(tenant_id, space_id, actor_id, _MANAGE_ROLES)
        if not await self.repository.delete_shared_knowledge(
            tenant_id, space_id, reference
        ):
            raise NotFoundError(f"shared knowledge base not found: {reference}")

    async def has_knowledge_access(
        self,
        tenant_id: str,
        user_id: str,
        space_ids: tuple[str, ...],
        reference: str,
    ) -> bool:
        for space_id in space_ids:
            if await self.repository.get_member(tenant_id, space_id, user_id) is None:
                continue
            if any(
                item.knowledge_base_reference == reference
                for item in await self.repository.list_shared_knowledge(tenant_id, space_id)
            ):
                return True
        return False

    # ------------------------------------------------------------------
    # User groups
    # ------------------------------------------------------------------

    async def create_group(
        self, tenant_id: str, actor_id: str, name: str, description: str = ""
    ) -> UserGroup:
        now = self._clock()
        group = UserGroup(
            tenantId=tenant_id,
            groupId=self._ids("group"),
            name=name.strip(),
            description=description.strip(),
            createdBy=actor_id,
            createdAt=now,
        )
        if not group.name:
            raise ConflictError("user group name must not be empty")
        await self._workspace_agents.add_group(group)
        return group

    async def list_groups(self, tenant_id: str) -> list[UserGroup]:
        return await self._workspace_agents.list_groups(tenant_id)

    async def get_group(
        self, tenant_id: str, group_id: str
    ) -> tuple[UserGroup, list[GroupMember]]:
        group = await self._workspace_agents.get_group(tenant_id, group_id)
        members = await self._workspace_agents.list_group_members(tenant_id, group_id)
        return group, members

    async def delete_group(self, tenant_id: str, group_id: str) -> None:
        if not await self._workspace_agents.delete_group(tenant_id, group_id):
            raise NotFoundError(f"user group not found: {group_id}")

    async def add_group_member(
        self, tenant_id: str, group_id: str, user_id: str
    ) -> GroupMember:
        await self._workspace_agents.get_group(tenant_id, group_id)
        member = GroupMember(
            tenantId=tenant_id,
            groupId=group_id,
            userId=user_id,
            createdAt=self._clock(),
        )
        try:
            await self._workspace_agents.add_group_member(member)
        except ConflictError:
            # Group membership is idempotent.
            return member
        return member

    async def remove_group_member(
        self, tenant_id: str, group_id: str, user_id: str
    ) -> None:
        if not await self._workspace_agents.delete_group_member(
            tenant_id, group_id, user_id
        ):
            raise NotFoundError(f"group member not found: {group_id}:{user_id}")

    # ------------------------------------------------------------------
    # Lifecycle: ownership transfer
    # ------------------------------------------------------------------

    async def transfer_agent(
        self,
        tenant_id: str,
        actor_id: str,
        agent_id: str,
        *,
        to_user_id: str | None = None,
        to_space_id: str | None = None,
    ) -> WorkspaceAgent:
        """Transfer a personal Agent to another user or hand it up to a space.

        personal -> personal re-keys immutable versions and drafts to the new
        owner while keeping the stable agent_id. personal -> workspace (上缴)
        moves the identity into the space; immutable versions keep their
        creator coordinates because Releases resolve them by source owner.
        """
        if (to_user_id is None) == (to_space_id is None):
            raise ConflictError("provide exactly one of to_user_id or to_space_id")
        agent = await self._workspace_agents.get_agent(tenant_id, agent_id)
        if agent.scope is not AgentScope.PERSONAL:
            raise ConflictError("only personal Agents can be transferred")
        if agent.owner_user_id != actor_id:
            raise PermissionDeniedError("only the current owner can transfer an Agent")
        assert agent.owner_user_id is not None
        now = self._clock()
        if to_user_id is not None:
            if to_user_id == agent.owner_user_id:
                return agent
            existing = await self._workspace_agents.get_personal_agent(
                tenant_id, to_user_id, agent.name
            )
            if existing is not None:
                raise ConflictError(
                    f"target user already owns an Agent named {agent.name}"
                )
            moved_versions = await self._agents.move_owner(
                tenant_id, agent.owner_user_id, to_user_id, agent.name
            )
            moved_drafts = 0
            if self._drafts is not None:
                moved_drafts = await self._drafts.move_owner(
                    tenant_id, agent.owner_user_id, to_user_id, agent.name
                )
            updated = agent.model_copy(
                update={
                    "owner_user_id": to_user_id,
                    "updated_at": now,
                }
            )
        else:
            assert to_space_id is not None
            await self._require_member(tenant_id, to_space_id, actor_id)
            existing = await self._workspace_agents.get_workspace_agent(
                tenant_id, to_space_id, agent.name
            )
            if existing is not None:
                raise ConflictError(
                    f"target space already owns an Agent named {agent.name}"
                )
            moved_versions = 0
            moved_drafts = 0
            updated = agent.model_copy(
                update={
                    "scope": AgentScope.WORKSPACE,
                    "owner_user_id": None,
                    "space_id": to_space_id,
                    "updated_at": now,
                }
            )
        await self._workspace_agents.update_agent(updated)
        await self._record_audit(
            tenant_id=tenant_id,
            user_id=actor_id,
            action="agent.transfer",
            resource_type="workspace_agent",
            resource_id=agent.agent_id,
            details={
                "name": agent.name,
                "from_owner": agent.owner_user_id,
                "to_user_id": to_user_id,
                "to_space_id": to_space_id,
                "moved_versions": moved_versions,
                "moved_drafts": moved_drafts,
            },
        )
        return updated

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    async def _require_member(
        self, tenant_id: str, space_id: str, user_id: str
    ) -> TeamSpaceMember:
        member = await self.repository.get_member(tenant_id, space_id, user_id)
        if member is None:
            raise NotFoundError(f"team space not found: {space_id}")
        return member

    async def _require_role(
        self,
        tenant_id: str,
        space_id: str,
        user_id: str,
        roles: frozenset[SpaceRole],
    ) -> TeamSpaceMember:
        member = await self._require_member(tenant_id, space_id, user_id)
        if member.role not in roles:
            raise PermissionDeniedError("team space role does not allow this action")
        return member
