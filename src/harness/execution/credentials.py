"""Run-scoped short-lived credentials without durable secret material."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from harness.core.models import ExecutionIdentity
from harness.runtime.mcp_credentials import CredentialValues, DynamicMcpCredentialProvider


class CredentialLeaseError(RuntimeError):
    """A credential lease is absent, expired, revoked or out of scope."""


class CredentialResourceKind(StrEnum):
    MODEL = "model"
    MCP = "mcp"


class CredentialLease(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    lease_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    resource_kind: CredentialResourceKind
    resource_reference: str = Field(min_length=1)
    secret_reference: str = Field(min_length=1)
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    values: Mapping[str, SecretStr] = Field(exclude=True, repr=False)

    def audit_record(self) -> dict[str, str]:
        return {
            "lease_id": self.lease_id,
            "run_id": self.run_id,
            "resource_kind": self.resource_kind.value,
            "resource_reference": self.resource_reference,
            "secret_reference": self.secret_reference,
            "expires_at": self.expires_at.isoformat(),
        }


class CredentialBroker(Protocol):
    async def issue(
        self,
        *,
        identity: ExecutionIdentity,
        resource_kind: CredentialResourceKind,
        resource_reference: str,
        required_keys: frozenset[str],
        ttl_seconds: int = 300,
    ) -> CredentialLease: ...

    async def resolve(
        self, lease_id: str, identity: ExecutionIdentity
    ) -> CredentialValues: ...

    async def revoke_run(self, tenant_id: str, run_id: str) -> None: ...


class CredentialLeaseMaintenance(Protocol):
    """Optional control-plane maintenance surface for a credential broker."""

    async def reap_expired(self) -> int: ...

    async def active_lease_count(self) -> int: ...


type CredentialSourceKey = tuple[str, CredentialResourceKind, str]


class InMemoryCredentialBroker:
    """Reference implementation; only lease metadata is safe to persist or audit."""

    def __init__(
        self,
        sources: Mapping[
            CredentialSourceKey, tuple[str, Mapping[str, SecretStr]]
        ],
        *,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[], str] | None = None,
        max_ttl_seconds: int = 900,
    ) -> None:
        self._sources = {
            key: (reference, MappingProxyType(dict(values)))
            for key, (reference, values) in sources.items()
        }
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids = id_generator or (lambda: f"credential_lease_{uuid4().hex}")
        self._max_ttl_seconds = max_ttl_seconds
        self._leases: dict[str, CredentialLease] = {}

    async def issue(
        self,
        *,
        identity: ExecutionIdentity,
        resource_kind: CredentialResourceKind,
        resource_reference: str,
        required_keys: frozenset[str],
        ttl_seconds: int = 300,
    ) -> CredentialLease:
        if ttl_seconds < 1 or ttl_seconds > self._max_ttl_seconds:
            raise CredentialLeaseError("credential lease TTL is outside platform bounds")
        source = self._sources.get(
            (identity.tenant_id, resource_kind, resource_reference)
        ) or self._sources.get(
            ("*", resource_kind, resource_reference)
        )
        if source is None:
            raise CredentialLeaseError("credential reference is unavailable")
        secret_reference, values = source
        missing = sorted(required_keys.difference(values))
        if missing:
            raise CredentialLeaseError(
                "credential reference is missing required keys: " + ", ".join(missing)
            )
        now = self._clock()
        lease = CredentialLease(
            lease_id=self._ids(),
            tenant_id=identity.tenant_id,
            run_id=identity.run_id,
            resource_kind=resource_kind,
            resource_reference=resource_reference,
            secret_reference=secret_reference,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            values=MappingProxyType({key: values[key] for key in required_keys}),
        )
        self._leases[lease.lease_id] = lease
        return lease

    async def resolve(
        self, lease_id: str, identity: ExecutionIdentity
    ) -> CredentialValues:
        lease = self._leases.get(lease_id)
        if lease is None:
            raise CredentialLeaseError("credential lease does not exist")
        if lease.tenant_id != identity.tenant_id or lease.run_id != identity.run_id:
            raise CredentialLeaseError("credential lease workload identity mismatch")
        if lease.revoked_at is not None:
            raise CredentialLeaseError("credential lease is revoked")
        if self._clock() >= lease.expires_at:
            raise CredentialLeaseError("credential lease is expired")
        return MappingProxyType(dict(lease.values))

    async def revoke_run(self, tenant_id: str, run_id: str) -> None:
        now = self._clock()
        for lease_id, lease in tuple(self._leases.items()):
            if lease.tenant_id == tenant_id and lease.run_id == run_id:
                self._leases[lease_id] = lease.model_copy(update={"revoked_at": now})

    async def reap_expired(self) -> int:
        now = self._clock()
        expired = [
            lease_id
            for lease_id, lease in self._leases.items()
            if lease.revoked_at is not None or lease.expires_at <= now
        ]
        for lease_id in expired:
            del self._leases[lease_id]
        return len(expired)

    async def active_lease_count(self) -> int:
        now = self._clock()
        return sum(
            lease.revoked_at is None and lease.expires_at > now
            for lease in self._leases.values()
        )


class BrokerMcpCredentialProvider(DynamicMcpCredentialProvider):
    """Issue a fresh run-scoped MCP lease at tool-resolution time."""

    def __init__(self, broker: CredentialBroker, *, ttl_seconds: int = 300) -> None:
        self._broker = broker
        self._ttl_seconds = ttl_seconds
        self.issued_lease_ids: dict[tuple[str, str], str] = {}

    async def resolve(
        self,
        server_reference: str,
        identity: ExecutionIdentity,
        required_keys: frozenset[str],
    ) -> CredentialValues:
        lease = await self._broker.issue(
            identity=identity,
            resource_kind=CredentialResourceKind.MCP,
            resource_reference=server_reference,
            required_keys=required_keys,
            ttl_seconds=self._ttl_seconds,
        )
        self.issued_lease_ids[(identity.run_id, server_reference)] = lease.lease_id
        return await self._broker.resolve(lease.lease_id, identity)
