from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.governance.models import (
    CredentialConnection,
    GovernedPolicyProfile,
    PolicyPublication,
)


class GovernanceRepository(Protocol):
    async def add_connection(self, value: CredentialConnection) -> None: ...

    async def get_connection(self, tenant_id: str, connection_id: str) -> CredentialConnection: ...

    async def list_connections(
        self,
        tenant_id: str,
        *,
        resource_kind: str | None = None,
        resource_reference: str | None = None,
    ) -> Sequence[CredentialConnection]: ...

    async def compare_and_set_connection(
        self, expected_revision: int, value: CredentialConnection
    ) -> bool: ...

    async def add_policy(self, value: GovernedPolicyProfile) -> None: ...

    async def get_policy(self, tenant_id: str, policy_id: str) -> GovernedPolicyProfile: ...

    async def list_policies(self, tenant_id: str) -> Sequence[GovernedPolicyProfile]: ...

    async def compare_and_set_policy(
        self, expected_revision: int, value: GovernedPolicyProfile
    ) -> bool: ...

    async def publish_policy(
        self,
        *,
        expected_revision: int,
        profile: GovernedPolicyProfile,
        publication: PolicyPublication,
    ) -> bool: ...

    async def get_publication(
        self, tenant_id: str, policy_id: str, revision: int
    ) -> PolicyPublication: ...

    async def list_publications(
        self, tenant_id: str, policy_id: str
    ) -> Sequence[PolicyPublication]: ...


class InMemoryGovernanceRepository:
    def __init__(self) -> None:
        self._connections: dict[tuple[str, str], CredentialConnection] = {}
        self._policies: dict[tuple[str, str], GovernedPolicyProfile] = {}
        self._publications: dict[tuple[str, str, int], PolicyPublication] = {}
        self._lock = asyncio.Lock()

    async def add_connection(self, value: CredentialConnection) -> None:
        key = (value.tenant_id, value.connection_id)
        async with self._lock:
            if key in self._connections:
                raise ConflictError(f"credential connection already exists: {value.connection_id}")
            self._connections[key] = value

    async def get_connection(self, tenant_id: str, connection_id: str) -> CredentialConnection:
        try:
            return self._connections[(tenant_id, connection_id)]
        except KeyError as error:
            raise NotFoundError(f"credential connection not found: {connection_id}") from error

    async def list_connections(
        self,
        tenant_id: str,
        *,
        resource_kind: str | None = None,
        resource_reference: str | None = None,
    ) -> Sequence[CredentialConnection]:
        values = [
            value
            for (stored_tenant, _), value in self._connections.items()
            if stored_tenant == tenant_id
            and (resource_kind is None or value.resource_kind.value == resource_kind)
            and (
                resource_reference is None
                or value.resource_reference == resource_reference
            )
        ]
        return tuple(sorted(values, key=lambda value: value.connection_id))

    async def compare_and_set_connection(
        self, expected_revision: int, value: CredentialConnection
    ) -> bool:
        if value.revision != expected_revision + 1:
            raise ConflictError("credential connection revision must increment by one")
        key = (value.tenant_id, value.connection_id)
        async with self._lock:
            current = self._connections.get(key)
            if current is None:
                raise NotFoundError(
                    f"credential connection not found: {value.connection_id}"
                )
            if current.revision != expected_revision:
                return False
            self._connections[key] = value
            return True

    async def add_policy(self, value: GovernedPolicyProfile) -> None:
        key = (value.tenant_id, value.policy_id)
        async with self._lock:
            if key in self._policies:
                raise ConflictError(f"governed policy already exists: {value.policy_id}")
            self._policies[key] = value

    async def get_policy(self, tenant_id: str, policy_id: str) -> GovernedPolicyProfile:
        try:
            return self._policies[(tenant_id, policy_id)]
        except KeyError as error:
            raise NotFoundError(f"governed policy not found: {policy_id}") from error

    async def list_policies(self, tenant_id: str) -> Sequence[GovernedPolicyProfile]:
        values = [
            value
            for (stored_tenant, _), value in self._policies.items()
            if stored_tenant == tenant_id
        ]
        return tuple(sorted(values, key=lambda value: value.policy_id))

    async def compare_and_set_policy(
        self, expected_revision: int, value: GovernedPolicyProfile
    ) -> bool:
        if value.revision != expected_revision + 1:
            raise ConflictError("governed policy revision must increment by one")
        key = (value.tenant_id, value.policy_id)
        async with self._lock:
            current = self._policies.get(key)
            if current is None:
                raise NotFoundError(f"governed policy not found: {value.policy_id}")
            if current.revision != expected_revision:
                return False
            self._policies[key] = value
            return True

    async def publish_policy(
        self,
        *,
        expected_revision: int,
        profile: GovernedPolicyProfile,
        publication: PolicyPublication,
    ) -> bool:
        key = (profile.tenant_id, profile.policy_id)
        publication_key = (
            publication.tenant_id,
            publication.policy_id,
            publication.revision,
        )
        async with self._lock:
            current = self._policies.get(key)
            if current is None:
                raise NotFoundError(f"governed policy not found: {profile.policy_id}")
            if current.revision != expected_revision:
                return False
            if publication_key in self._publications:
                raise ConflictError(
                    f"governed policy publication already exists: {publication.revision}"
                )
            self._publications[publication_key] = publication
            self._policies[key] = profile
            return True

    async def get_publication(
        self, tenant_id: str, policy_id: str, revision: int
    ) -> PolicyPublication:
        try:
            return self._publications[(tenant_id, policy_id, revision)]
        except KeyError as error:
            raise NotFoundError(
                f"governed policy publication not found: {policy_id}@{revision}"
            ) from error

    async def list_publications(
        self, tenant_id: str, policy_id: str
    ) -> Sequence[PolicyPublication]:
        values = [
            value
            for (stored_tenant, stored_policy, _), value in self._publications.items()
            if stored_tenant == tenant_id and stored_policy == policy_id
        ]
        return tuple(sorted(values, key=lambda value: value.revision, reverse=True))
