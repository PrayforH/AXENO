"""Persistence ports and in-memory implementation for workspace Agents."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from harness.core.errors import ConflictError, NotFoundError
from harness.sharing.models import (
    AgentAcl,
    AgentPermission,
    AgentRelease,
    AgentScope,
    GranteeType,
    WorkspaceAgent,
)


class WorkspaceAgentRepository(Protocol):
    async def add_agent(self, agent: WorkspaceAgent) -> None: ...
    async def get_agent(self, tenant_id: str, agent_id: str) -> WorkspaceAgent: ...
    async def get_personal_agent(
        self, tenant_id: str, owner_user_id: str, name: str
    ) -> WorkspaceAgent | None: ...
    async def get_workspace_agent(
        self, tenant_id: str, space_id: str, name: str
    ) -> WorkspaceAgent | None: ...
    async def list_agents_for_space(
        self, tenant_id: str, space_id: str
    ) -> list[WorkspaceAgent]: ...
    async def list_personal_agents(
        self, tenant_id: str, owner_user_id: str
    ) -> list[WorkspaceAgent]: ...
    async def update_agent(self, agent: WorkspaceAgent) -> None: ...
    async def add_release(self, release: AgentRelease) -> None: ...
    async def get_release(
        self, tenant_id: str, space_id: str, agent_id: str, version: str
    ) -> AgentRelease: ...
    async def get_release_by_source(
        self,
        tenant_id: str,
        space_id: str,
        source_owner_user_id: str,
        source_name: str,
        version: str,
    ) -> AgentRelease | None: ...
    async def list_releases(
        self, tenant_id: str, space_id: str, agent_id: str
    ) -> list[AgentRelease]: ...
    async def delete_release(
        self, tenant_id: str, space_id: str, agent_id: str, version: str
    ) -> bool: ...
    async def add_acl(self, acl: AgentAcl) -> None: ...
    async def list_acls(self, tenant_id: str, agent_id: str) -> list[AgentAcl]: ...
    async def delete_acl(
        self,
        tenant_id: str,
        agent_id: str,
        grantee_type: GranteeType,
        grantee_id: str,
        permission: AgentPermission,
    ) -> bool: ...


class InMemoryWorkspaceAgentRepository:
    def __init__(self) -> None:
        self._agents: dict[tuple[str, str], WorkspaceAgent] = {}
        self._releases: dict[tuple[str, str, str, str], AgentRelease] = {}
        self._acls: dict[tuple[str, str, str, str, str], AgentAcl] = {}
        self._lock = asyncio.Lock()

    async def add_agent(self, agent: WorkspaceAgent) -> None:
        key = (agent.tenant_id, agent.agent_id)
        async with self._lock:
            if key in self._agents:
                raise ConflictError(f"workspace agent already exists: {agent.agent_id}")
            self._agents[key] = agent

    async def get_agent(self, tenant_id: str, agent_id: str) -> WorkspaceAgent:
        try:
            return self._agents[(tenant_id, agent_id)]
        except KeyError as error:
            raise NotFoundError(f"workspace agent not found: {agent_id}") from error

    async def get_personal_agent(
        self, tenant_id: str, owner_user_id: str, name: str
    ) -> WorkspaceAgent | None:
        for agent in self._agents.values():
            if (
                agent.tenant_id == tenant_id
                and agent.scope is AgentScope.PERSONAL
                and agent.owner_user_id == owner_user_id
                and agent.name == name
            ):
                return agent
        return None

    async def get_workspace_agent(
        self, tenant_id: str, space_id: str, name: str
    ) -> WorkspaceAgent | None:
        for agent in self._agents.values():
            if (
                agent.tenant_id == tenant_id
                and agent.scope is AgentScope.WORKSPACE
                and agent.space_id == space_id
                and agent.name == name
            ):
                return agent
        return None

    async def list_agents_for_space(
        self, tenant_id: str, space_id: str
    ) -> list[WorkspaceAgent]:
        return sorted(
            [
                agent
                for agent in self._agents.values()
                if agent.tenant_id == tenant_id
                and agent.scope is AgentScope.WORKSPACE
                and agent.space_id == space_id
            ],
            key=lambda item: (item.name, item.agent_id),
        )

    async def list_personal_agents(
        self, tenant_id: str, owner_user_id: str
    ) -> list[WorkspaceAgent]:
        return sorted(
            [
                agent
                for agent in self._agents.values()
                if agent.tenant_id == tenant_id
                and agent.scope is AgentScope.PERSONAL
                and agent.owner_user_id == owner_user_id
            ],
            key=lambda item: (item.name, item.agent_id),
        )

    async def update_agent(self, agent: WorkspaceAgent) -> None:
        key = (agent.tenant_id, agent.agent_id)
        if key not in self._agents:
            raise NotFoundError(f"workspace agent not found: {agent.agent_id}")
        self._agents[key] = agent

    async def add_release(self, release: AgentRelease) -> None:
        key = (release.tenant_id, release.space_id, release.agent_id, release.version)
        async with self._lock:
            if key in self._releases:
                raise ConflictError(
                    f"agent release already exists: {release.agent_id}@{release.version}"
                )
            self._releases[key] = release

    async def get_release(
        self, tenant_id: str, space_id: str, agent_id: str, version: str
    ) -> AgentRelease:
        try:
            return self._releases[(tenant_id, space_id, agent_id, version)]
        except KeyError as error:
            raise NotFoundError(
                f"agent release not found: {agent_id}@{version}"
            ) from error

    async def get_release_by_source(
        self,
        tenant_id: str,
        space_id: str,
        source_owner_user_id: str,
        source_name: str,
        version: str,
    ) -> AgentRelease | None:
        for release in self._releases.values():
            if (
                release.tenant_id == tenant_id
                and release.space_id == space_id
                and release.source_owner_user_id == source_owner_user_id
                and release.source_name == source_name
                and release.version == version
            ):
                return release
        return None

    async def list_releases(
        self, tenant_id: str, space_id: str, agent_id: str
    ) -> list[AgentRelease]:
        return sorted(
            [
                release
                for release in self._releases.values()
                if release.tenant_id == tenant_id
                and release.space_id == space_id
                and release.agent_id == agent_id
            ],
            key=lambda item: item.version,
        )

    async def delete_release(
        self, tenant_id: str, space_id: str, agent_id: str, version: str
    ) -> bool:
        return (
            self._releases.pop((tenant_id, space_id, agent_id, version), None)
            is not None
        )

    async def add_acl(self, acl: AgentAcl) -> None:
        key = (
            acl.tenant_id,
            acl.agent_id,
            acl.grantee_type.value,
            acl.grantee_id,
            acl.permission.value,
        )
        async with self._lock:
            if key in self._acls:
                raise ConflictError(
                    f"agent ACL already exists: {acl.agent_id} {acl.grantee_type.value}"
                    f":{acl.grantee_id} {acl.permission.value}"
                )
            self._acls[key] = acl

    async def list_acls(self, tenant_id: str, agent_id: str) -> list[AgentAcl]:
        return sorted(
            [
                acl
                for (stored_tenant, stored_agent, *_rest), acl in self._acls.items()
                if stored_tenant == tenant_id and stored_agent == agent_id
            ],
            key=lambda item: (item.grantee_type.value, item.grantee_id, item.permission.value),
        )

    async def delete_acl(
        self,
        tenant_id: str,
        agent_id: str,
        grantee_type: GranteeType,
        grantee_id: str,
        permission: AgentPermission,
    ) -> bool:
        return (
            self._acls.pop(
                (tenant_id, agent_id, grantee_type.value, grantee_id, permission.value),
                None,
            )
            is not None
        )


class AgentIdentityService:
    """Assigns stable personal Agent identities to publications without one."""

    def __init__(
        self,
        repository: WorkspaceAgentRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._ids: Callable[[str], str] = id_generator or (
            lambda prefix: f"{prefix}_{uuid4().hex}"
        )

    async def get_or_create_personal_agent_id(
        self, tenant_id: str, owner_user_id: str, name: str
    ) -> str:
        existing = await self._repository.get_personal_agent(
            tenant_id, owner_user_id, name
        )
        if existing is not None:
            return existing.agent_id
        now = self._clock()
        agent = WorkspaceAgent(
            tenantId=tenant_id,
            agentId=self._ids("agent"),
            scope=AgentScope.PERSONAL,
            ownerUserId=owner_user_id,
            name=name,
            createdBy=owner_user_id,
            createdAt=now,
            updatedAt=now,
        )
        try:
            await self._repository.add_agent(agent)
        except ConflictError:
            # A concurrent publication won the race; reuse its identity.
            existing = await self._repository.get_personal_agent(
                tenant_id, owner_user_id, name
            )
            if existing is not None:
                return existing.agent_id
            raise
        return agent.agent_id
