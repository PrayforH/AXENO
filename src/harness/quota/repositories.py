from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.quota.models import (
    QuotaCounter,
    QuotaPolicy,
    QuotaResource,
    ReservationState,
    ResourceReservation,
    UsageLedgerEntry,
)


class QuotaExceededError(ConflictError):
    def __init__(self, *, resource: QuotaResource, limit: int, requested: int, used: int) -> None:
        self.resource = resource
        self.limit = limit
        self.requested = requested
        self.used = used
        super().__init__(
            f"quota_exceeded:{resource.value}: limit={limit} used={used} requested={requested}"
        )


class QuotaRepository(Protocol):
    async def list_policies(self, tenant_id: str) -> Sequence[QuotaPolicy]: ...

    async def replace_policy(
        self, policy: QuotaPolicy, *, expected_revision: int
    ) -> QuotaPolicy: ...

    async def reserve(
        self, reservation: ResourceReservation, *, window_key: str
    ) -> ResourceReservation: ...

    async def get_reservation(
        self, tenant_id: str, idempotency_key: str
    ) -> ResourceReservation | None: ...

    async def commit(
        self,
        tenant_id: str,
        reservation_id: str,
        *,
        amount: int,
        window_key: str,
        ledger: UsageLedgerEntry,
    ) -> ResourceReservation: ...

    async def release(
        self,
        tenant_id: str,
        reservation_id: str,
        *,
        state: ReservationState,
        window_key: str,
    ) -> ResourceReservation: ...

    async def add_ledger(self, entry: UsageLedgerEntry) -> None: ...

    async def list_counters(self, tenant_id: str) -> Sequence[QuotaCounter]: ...

    async def list_active_reservations(self, tenant_id: str) -> Sequence[ResourceReservation]: ...

    async def list_expired_active(
        self, now: datetime, *, limit: int
    ) -> Sequence[ResourceReservation]: ...

    async def list_ledger(self, tenant_id: str) -> Sequence[UsageLedgerEntry]: ...


class InMemoryQuotaRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._policies: dict[tuple[str, str], QuotaPolicy] = {}
        self._reservations: dict[tuple[str, str], ResourceReservation] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._counters: dict[tuple[str, str, QuotaResource, str], QuotaCounter] = {}
        self._ledger: dict[tuple[str, str], UsageLedgerEntry] = {}

    async def list_policies(self, tenant_id: str) -> Sequence[QuotaPolicy]:
        return tuple(
            policy
            for (stored_tenant, _), policy in self._policies.items()
            if stored_tenant == tenant_id
        )

    async def replace_policy(self, policy: QuotaPolicy, *, expected_revision: int) -> QuotaPolicy:
        async with self._lock:
            key = (policy.tenant_id, policy.policy_id)
            current = self._policies.get(key)
            actual = current.revision if current is not None else 0
            if actual != expected_revision:
                raise ConflictError(
                    f"quota policy revision changed: expected={expected_revision} actual={actual}"
                )
            self._policies[key] = policy
            return policy

    async def reserve(
        self, reservation: ResourceReservation, *, window_key: str
    ) -> ResourceReservation:
        async with self._lock:
            idempotency = (reservation.tenant_id, reservation.idempotency_key)
            existing_id = self._idempotency.get(idempotency)
            if existing_id is not None:
                existing = self._reservations[(reservation.tenant_id, existing_id)]
                if (
                    existing.resource != reservation.resource
                    or existing.amount != reservation.amount
                    or existing.constraints != reservation.constraints
                    or existing.subject_id != reservation.subject_id
                ):
                    raise ConflictError("quota reservation idempotency key was reused")
                return existing
            for constraint in reservation.constraints:
                key = (
                    reservation.tenant_id,
                    constraint.scope_key,
                    reservation.resource,
                    window_key,
                )
                current = self._counters.get(
                    key,
                    QuotaCounter(
                        tenantId=reservation.tenant_id,
                        scopeKey=constraint.scope_key,
                        resource=reservation.resource,
                        windowKey=window_key,
                        reserved=0,
                        committed=0,
                        limit=constraint.limit,
                    ),
                )
                used = current.reserved + current.committed
                if used + reservation.amount > constraint.limit:
                    raise QuotaExceededError(
                        resource=reservation.resource,
                        limit=constraint.limit,
                        requested=reservation.amount,
                        used=used,
                    )
            for constraint in reservation.constraints:
                key = (
                    reservation.tenant_id,
                    constraint.scope_key,
                    reservation.resource,
                    window_key,
                )
                current = self._counters.get(
                    key,
                    QuotaCounter(
                        tenantId=reservation.tenant_id,
                        scopeKey=constraint.scope_key,
                        resource=reservation.resource,
                        windowKey=window_key,
                        reserved=0,
                        committed=0,
                        limit=constraint.limit,
                    ),
                )
                self._counters[key] = current.model_copy(
                    update={
                        "reserved": current.reserved + reservation.amount,
                        "limit": constraint.limit,
                    }
                )
            self._reservations[(reservation.tenant_id, reservation.reservation_id)] = reservation
            self._idempotency[idempotency] = reservation.reservation_id
            return reservation

    async def get_reservation(
        self, tenant_id: str, idempotency_key: str
    ) -> ResourceReservation | None:
        reservation_id = self._idempotency.get((tenant_id, idempotency_key))
        return (
            self._reservations.get((tenant_id, reservation_id))
            if reservation_id is not None
            else None
        )

    async def commit(
        self,
        tenant_id: str,
        reservation_id: str,
        *,
        amount: int,
        window_key: str,
        ledger: UsageLedgerEntry,
    ) -> ResourceReservation:
        async with self._lock:
            key = (tenant_id, reservation_id)
            reservation = self._reservations.get(key)
            if reservation is None:
                raise NotFoundError(f"quota reservation not found: {reservation_id}")
            if reservation.state is ReservationState.COMMITTED:
                return reservation
            if reservation.state is not ReservationState.ACTIVE:
                raise ConflictError("quota reservation is not active")
            if amount < 0:
                raise ValueError("committed amount must not be negative")
            for constraint in reservation.constraints:
                counter_key = (
                    tenant_id,
                    constraint.scope_key,
                    reservation.resource,
                    window_key,
                )
                current = self._counters[counter_key]
                self._counters[counter_key] = current.model_copy(
                    update={
                        "reserved": current.reserved - reservation.amount,
                        "committed": current.committed + amount,
                    }
                )
            committed = reservation.model_copy(
                update={
                    "state": ReservationState.COMMITTED,
                    "completed_at": ledger.occurred_at,
                }
            )
            self._reservations[key] = committed
            self._ledger[(tenant_id, ledger.entry_id)] = ledger
            return committed

    async def release(
        self,
        tenant_id: str,
        reservation_id: str,
        *,
        state: ReservationState,
        window_key: str,
    ) -> ResourceReservation:
        if state not in {ReservationState.RELEASED, ReservationState.EXPIRED}:
            raise ValueError("release state must be released or expired")
        async with self._lock:
            key = (tenant_id, reservation_id)
            reservation = self._reservations.get(key)
            if reservation is None:
                raise NotFoundError(f"quota reservation not found: {reservation_id}")
            if reservation.state is not ReservationState.ACTIVE:
                return reservation
            for constraint in reservation.constraints:
                counter_key = (
                    tenant_id,
                    constraint.scope_key,
                    reservation.resource,
                    window_key,
                )
                current = self._counters[counter_key]
                self._counters[counter_key] = current.model_copy(
                    update={"reserved": current.reserved - reservation.amount}
                )
            released = reservation.model_copy(
                update={"state": state, "completed_at": reservation.expires_at}
            )
            self._reservations[key] = released
            return released

    async def add_ledger(self, entry: UsageLedgerEntry) -> None:
        async with self._lock:
            self._ledger.setdefault((entry.tenant_id, entry.entry_id), entry)

    async def list_counters(self, tenant_id: str) -> Sequence[QuotaCounter]:
        return tuple(
            counter
            for (stored_tenant, *_), counter in self._counters.items()
            if stored_tenant == tenant_id
        )

    async def list_active_reservations(self, tenant_id: str) -> Sequence[ResourceReservation]:
        return tuple(
            reservation
            for (stored_tenant, _), reservation in self._reservations.items()
            if stored_tenant == tenant_id and reservation.state is ReservationState.ACTIVE
        )

    async def list_ledger(self, tenant_id: str) -> Sequence[UsageLedgerEntry]:
        return tuple(
            entry
            for (stored_tenant, _), entry in self._ledger.items()
            if stored_tenant == tenant_id
        )

    async def list_expired_active(
        self, now: datetime, *, limit: int
    ) -> Sequence[ResourceReservation]:
        return tuple(
            reservation
            for reservation in self._reservations.values()
            if reservation.state is ReservationState.ACTIVE and reservation.expires_at <= now
        )[:limit]
