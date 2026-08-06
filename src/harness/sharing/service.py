"""Team-space RBAC and immutable Agent-version grants."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from harness.application.types import Clock, IdGenerator
from harness.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from harness.core.models import AgentVersion, AgentVersionStatus
from harness.core.ports import AgentRegistry
from harness.sharing.models import (
    SharedAgentVersion,
    SharedKnowledgeBase,
    SpaceRole,
    TeamSpace,
    TeamSpaceMember,
)
from harness.sharing.repositories import TeamSpaceRepository

_MANAGE_ROLES = frozenset({SpaceRole.OWNER, SpaceRole.ADMIN})
_PUBLISH_ROLES = frozenset({SpaceRole.OWNER, SpaceRole.ADMIN, SpaceRole.CONTRIBUTOR})


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class TeamSpaceService:
    def __init__(
        self,
        repository: TeamSpaceRepository,
        agents: AgentRegistry,
        *,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self.repository = repository
        self._agents = agents
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._ids: IdGenerator = id_generator or _id

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
    ) -> SharedAgentVersion:
        await self._require_role(tenant_id, space_id, actor_id, _PUBLISH_ROLES)
        if owner_user_id != actor_id:
            raise PermissionDeniedError("users can only share their own Agents")
        agent = await self._agents.get(tenant_id, owner_user_id, name, version)
        if agent.status is not AgentVersionStatus.PUBLISHED:
            raise ConflictError("only published Agent versions can be shared")
        shared = SharedAgentVersion(
            tenantId=tenant_id,
            spaceId=space_id,
            agentOwnerUserId=owner_user_id,
            agentName=name,
            agentVersion=version,
            sharedBy=actor_id,
            runnableByViewer=runnable_by_viewer,
            createdAt=self._clock(),
        )
        await self.repository.add_shared_agent(shared)
        return shared

    async def unshare_agent(
        self,
        tenant_id: str,
        actor_id: str,
        space_id: str,
        owner_user_id: str,
        name: str,
        version: str,
    ) -> None:
        member = await self._require_role(tenant_id, space_id, actor_id, _PUBLISH_ROLES)
        if member.role is SpaceRole.CONTRIBUTOR and owner_user_id != actor_id:
            raise PermissionDeniedError("contributors can only unshare their own Agents")
        deleted = await self.repository.delete_shared_agent(
            tenant_id, space_id, owner_user_id, name, version
        )
        if not deleted:
            raise NotFoundError(f"shared agent not found: {name}@{version}")

    async def list_agents(
        self, tenant_id: str, user_id: str, space_id: str
    ) -> list[tuple[SharedAgentVersion, AgentVersion]]:
        await self._require_member(tenant_id, space_id, user_id)
        result: list[tuple[SharedAgentVersion, AgentVersion]] = []
        for shared in await self.repository.list_shared_agents(tenant_id, space_id):
            try:
                version = await self._agents.get(
                    tenant_id,
                    shared.agent_owner_user_id,
                    shared.agent_name,
                    shared.agent_version,
                )
            except NotFoundError:
                continue
            if version.status is AgentVersionStatus.PUBLISHED:
                result.append((shared, version))
        return result

    async def list_accessible_agents(
        self, tenant_id: str, user_id: str
    ) -> list[tuple[TeamSpace, TeamSpaceMember, SharedAgentVersion, AgentVersion]]:
        result: list[tuple[TeamSpace, TeamSpaceMember, SharedAgentVersion, AgentVersion]] = []
        for space in await self.repository.list_spaces_for_user(tenant_id, user_id):
            member = await self._require_member(tenant_id, space.space_id, user_id)
            for shared, agent in await self.list_agents(tenant_id, user_id, space.space_id):
                result.append((space, member, shared, agent))
        return result

    async def require_agent_access(
        self,
        tenant_id: str,
        user_id: str,
        space_id: str,
        owner_user_id: str,
        name: str,
        version: str,
    ) -> SharedAgentVersion:
        member = await self._require_member(tenant_id, space_id, user_id)
        shared = await self.repository.get_shared_agent(
            tenant_id, space_id, owner_user_id, name, version
        )
        if member.role is SpaceRole.VIEWER and not shared.runnable_by_viewer:
            raise PermissionDeniedError("viewers cannot run this shared Agent")
        return shared

    async def fork_agent(
        self,
        tenant_id: str,
        user_id: str,
        space_id: str,
        owner_user_id: str,
        name: str,
        version: str,
    ) -> AgentVersion:
        await self.require_agent_access(
            tenant_id, user_id, space_id, owner_user_id, name, version
        )
        source = await self._agents.get(tenant_id, owner_user_id, name, version)
        fork = source.model_copy(update={"owner_user_id": user_id, "created_at": self._clock()})
        try:
            await self._agents.add(fork)
        except ConflictError:
            existing = await self._agents.get(tenant_id, user_id, name, version)
            if existing.manifest_hash != source.manifest_hash:
                raise ConflictError(
                    f"personal Agent already exists with different content: {name}@{version}"
                ) from None
            return existing
        return fork

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
