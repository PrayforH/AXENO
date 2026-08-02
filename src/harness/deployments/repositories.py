"""Deployment persistence ports and in-memory adapters."""

from __future__ import annotations

import asyncio
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.deployments.models import (
    Deployment,
    DeploymentSnapshot,
    DeploymentStatus,
    Environment,
    EnvironmentName,
)


class EnvironmentRepository(Protocol):
    async def add(self, environment: Environment) -> None: ...
    async def get(
        self, tenant_id: str, owner_user_id: str, agent_name: str, name: EnvironmentName
    ) -> Environment: ...
    async def list_for_agent(
        self, tenant_id: str, owner_user_id: str, agent_name: str
    ) -> list[Environment]: ...
    async def compare_and_set(self, expected_revision: int, updated: Environment) -> bool: ...


class DeploymentRepository(Protocol):
    async def add_snapshot(self, snapshot: DeploymentSnapshot) -> None: ...
    async def get_snapshot(self, tenant_id: str, snapshot_id: str) -> DeploymentSnapshot: ...
    async def get_snapshot_for_user(
        self, tenant_id: str, owner_user_id: str, snapshot_id: str
    ) -> DeploymentSnapshot: ...
    async def list_snapshots(
        self, tenant_id: str, owner_user_id: str, agent_name: str
    ) -> list[DeploymentSnapshot]: ...
    async def add(self, deployment: Deployment) -> None: ...
    async def get(self, tenant_id: str, deployment_id: str) -> Deployment: ...
    async def get_for_user(
        self, tenant_id: str, owner_user_id: str, deployment_id: str
    ) -> Deployment: ...
    async def find_by_idempotency(
        self, tenant_id: str, owner_user_id: str, key: str
    ) -> Deployment | None: ...
    async def list_for_agent(
        self, tenant_id: str, owner_user_id: str, agent_name: str
    ) -> list[Deployment]: ...
    async def compare_and_set(self, expected: DeploymentStatus, updated: Deployment) -> bool: ...


class InMemoryEnvironmentRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str, EnvironmentName], Environment] = {}
        self._lock = asyncio.Lock()

    async def add(self, environment: Environment) -> None:
        key = (
            environment.tenant_id,
            environment.owner_user_id,
            environment.agent_name,
            environment.name,
        )
        async with self._lock:
            if key in self._items:
                raise ConflictError("Environment already exists")
            self._items[key] = environment

    async def get(
        self, tenant_id: str, owner_user_id: str, agent_name: str, name: EnvironmentName
    ) -> Environment:
        try:
            return self._items[(tenant_id, owner_user_id, agent_name, name)]
        except KeyError as error:
            raise NotFoundError(f"Environment not found: {agent_name}/{name}") from error

    async def list_for_agent(
        self, tenant_id: str, owner_user_id: str, agent_name: str
    ) -> list[Environment]:
        return sorted(
            (
                item
                for (t, owner, agent, _name), item in self._items.items()
                if t == tenant_id and owner == owner_user_id and agent == agent_name
            ),
            key=lambda item: item.name.value,
        )

    async def compare_and_set(self, expected_revision: int, updated: Environment) -> bool:
        key = (
            updated.tenant_id,
            updated.owner_user_id,
            updated.agent_name,
            updated.name,
        )
        async with self._lock:
            current = self._items.get(key)
            if current is None or current.revision != expected_revision:
                return False
            if updated.revision != expected_revision + 1:
                raise ConflictError("Environment revision must increment once")
            self._items[key] = updated
            return True


class InMemoryDeploymentRepository:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str], DeploymentSnapshot] = {}
        self._items: dict[tuple[str, str], Deployment] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._lock = asyncio.Lock()

    async def add_snapshot(self, snapshot: DeploymentSnapshot) -> None:
        key = (snapshot.tenant_id, snapshot.snapshot_id)
        async with self._lock:
            existing = self._snapshots.get(key)
            if existing is not None and existing != snapshot:
                raise ConflictError("Deployment Snapshot already exists")
            self._snapshots[key] = snapshot

    async def get_snapshot(self, tenant_id: str, snapshot_id: str) -> DeploymentSnapshot:
        try:
            return self._snapshots[(tenant_id, snapshot_id)]
        except KeyError as error:
            raise NotFoundError(f"Deployment Snapshot not found: {snapshot_id}") from error

    async def get_snapshot_for_user(
        self, tenant_id: str, owner_user_id: str, snapshot_id: str
    ) -> DeploymentSnapshot:
        value = await self.get_snapshot(tenant_id, snapshot_id)
        if value.created_by != owner_user_id:
            raise NotFoundError(f"Deployment Snapshot not found: {snapshot_id}")
        return value

    async def list_snapshots(
        self, tenant_id: str, owner_user_id: str, agent_name: str
    ) -> list[DeploymentSnapshot]:
        return sorted(
            (
                item
                for (t, _id), item in self._snapshots.items()
                if t == tenant_id
                and item.created_by == owner_user_id
                and item.agent_name == agent_name
            ),
            key=lambda item: (item.created_at, item.snapshot_id),
            reverse=True,
        )

    async def add(self, deployment: Deployment) -> None:
        key = (deployment.tenant_id, deployment.deployment_id)
        idem = (
            deployment.tenant_id,
            deployment.requested_by,
            deployment.idempotency_key,
        )
        async with self._lock:
            if key in self._items or idem in self._idempotency:
                raise ConflictError("Deployment already exists")
            self._items[key] = deployment
            self._idempotency[idem] = deployment.deployment_id

    async def get(self, tenant_id: str, deployment_id: str) -> Deployment:
        try:
            return self._items[(tenant_id, deployment_id)]
        except KeyError as error:
            raise NotFoundError(f"Deployment not found: {deployment_id}") from error

    async def get_for_user(
        self, tenant_id: str, owner_user_id: str, deployment_id: str
    ) -> Deployment:
        value = await self.get(tenant_id, deployment_id)
        if value.requested_by != owner_user_id:
            raise NotFoundError(f"Deployment not found: {deployment_id}")
        return value

    async def find_by_idempotency(
        self, tenant_id: str, owner_user_id: str, key: str
    ) -> Deployment | None:
        deployment_id = self._idempotency.get((tenant_id, owner_user_id, key))
        return None if deployment_id is None else self._items[(tenant_id, deployment_id)]

    async def list_for_agent(
        self, tenant_id: str, owner_user_id: str, agent_name: str
    ) -> list[Deployment]:
        return sorted(
            (
                item
                for (t, _id), item in self._items.items()
                if t == tenant_id
                and item.requested_by == owner_user_id
                and item.agent_name == agent_name
            ),
            key=lambda item: (item.created_at, item.deployment_id),
            reverse=True,
        )

    async def compare_and_set(self, expected: DeploymentStatus, updated: Deployment) -> bool:
        key = (updated.tenant_id, updated.deployment_id)
        async with self._lock:
            current = self._items.get(key)
            if current is None or current.status is not expected:
                return False
            if updated.fencing_token != current.fencing_token + 1:
                raise ConflictError("Deployment fencing token must increment once")
            self._items[key] = updated
            return True
