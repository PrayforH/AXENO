from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from harness.core.errors import ConflictError, NotFoundError
from harness.quota.models import (
    QuotaCounter,
    QuotaPolicy,
    QuotaResource,
    ReservationState,
    ResourceReservation,
    UsageLedgerEntry,
)
from harness.quota.repositories import QuotaExceededError
from harness.storage.database import SessionFactory
from harness.storage.models import (
    QuotaCounterRow,
    QuotaPolicyRow,
    QuotaReservationRow,
    UsageLedgerRow,
)


class PostgresQuotaRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def list_policies(self, tenant_id: str) -> Sequence[QuotaPolicy]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(QuotaPolicyRow).where(QuotaPolicyRow.tenant_id == tenant_id)
                )
            ).all()
            return tuple(QuotaPolicy.model_validate(row.payload) for row in rows)

    async def replace_policy(self, policy: QuotaPolicy, *, expected_revision: int) -> QuotaPolicy:
        async with self._sessions() as session:
            row = await session.scalar(
                select(QuotaPolicyRow)
                .where(
                    QuotaPolicyRow.tenant_id == policy.tenant_id,
                    QuotaPolicyRow.policy_id == policy.policy_id,
                )
                .with_for_update()
            )
            actual = row.revision if row is not None else 0
            if actual != expected_revision:
                raise ConflictError(
                    f"quota policy revision changed: expected={expected_revision} actual={actual}"
                )
            if row is None:
                session.add(
                    QuotaPolicyRow(
                        tenant_id=policy.tenant_id,
                        policy_id=policy.policy_id,
                        scope_key=policy.scope.key,
                        revision=policy.revision,
                        payload=policy.model_dump(mode="json", by_alias=True),
                    )
                )
            else:
                row.scope_key = policy.scope.key
                row.revision = policy.revision
                row.payload = policy.model_dump(mode="json", by_alias=True)
            await session.commit()
            return policy

    @staticmethod
    def _reservation(row: QuotaReservationRow) -> ResourceReservation:
        return ResourceReservation.model_validate(row.payload)

    async def get_reservation(
        self, tenant_id: str, idempotency_key: str
    ) -> ResourceReservation | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(QuotaReservationRow).where(
                    QuotaReservationRow.tenant_id == tenant_id,
                    QuotaReservationRow.idempotency_key == idempotency_key,
                )
            )
            return self._reservation(row) if row is not None else None

    @staticmethod
    def _same_reservation(existing: ResourceReservation, requested: ResourceReservation) -> bool:
        return (
            existing.resource == requested.resource
            and existing.amount == requested.amount
            and existing.constraints == requested.constraints
            and existing.subject_id == requested.subject_id
        )

    async def _locked_counter(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        scope_key: str,
        resource: QuotaResource,
        window_key: str,
        limit: int,
    ) -> QuotaCounterRow:
        await session.execute(
            pg_insert(QuotaCounterRow)
            .values(
                tenant_id=tenant_id,
                scope_key=scope_key,
                resource=resource.value,
                window_key=window_key,
                reserved=0,
                committed=0,
                limit_value=limit,
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing()
        )
        row = await session.scalar(
            select(QuotaCounterRow)
            .where(
                QuotaCounterRow.tenant_id == tenant_id,
                QuotaCounterRow.scope_key == scope_key,
                QuotaCounterRow.resource == resource.value,
                QuotaCounterRow.window_key == window_key,
            )
            .with_for_update()
        )
        assert row is not None
        return row

    async def reserve(
        self, reservation: ResourceReservation, *, window_key: str
    ) -> ResourceReservation:
        try:
            async with self._sessions() as session:
                existing_row = await session.scalar(
                    select(QuotaReservationRow)
                    .where(
                        QuotaReservationRow.tenant_id == reservation.tenant_id,
                        QuotaReservationRow.idempotency_key == reservation.idempotency_key,
                    )
                    .with_for_update()
                )
                if existing_row is not None:
                    existing = self._reservation(existing_row)
                    if not self._same_reservation(existing, reservation):
                        raise ConflictError("quota reservation idempotency key was reused")
                    return existing
                counters: list[QuotaCounterRow] = []
                for constraint in sorted(reservation.constraints, key=lambda item: item.scope_key):
                    counter = await self._locked_counter(
                        session,
                        tenant_id=reservation.tenant_id,
                        scope_key=constraint.scope_key,
                        resource=reservation.resource,
                        window_key=window_key,
                        limit=constraint.limit,
                    )
                    used = counter.reserved + counter.committed
                    if used + reservation.amount > constraint.limit:
                        raise QuotaExceededError(
                            resource=reservation.resource,
                            limit=constraint.limit,
                            requested=reservation.amount,
                            used=used,
                        )
                    counters.append(counter)
                for counter in counters:
                    counter.reserved += reservation.amount
                    counter.updated_at = datetime.now(UTC)
                session.add(
                    QuotaReservationRow(
                        tenant_id=reservation.tenant_id,
                        reservation_id=reservation.reservation_id,
                        idempotency_key=reservation.idempotency_key,
                        resource=reservation.resource.value,
                        amount=reservation.amount,
                        state=reservation.state.value,
                        expires_at=reservation.expires_at,
                        payload=reservation.model_dump(mode="json", by_alias=True),
                    )
                )
                await session.commit()
                return reservation
        except IntegrityError:
            existing = await self.get_reservation(
                reservation.tenant_id, reservation.idempotency_key
            )
            if existing is not None and self._same_reservation(existing, reservation):
                return existing
            raise ConflictError("quota reservation idempotency conflict") from None

    async def _active_reservation(
        self, session: AsyncSession, tenant_id: str, reservation_id: str
    ) -> tuple[QuotaReservationRow, ResourceReservation]:
        row = await session.scalar(
            select(QuotaReservationRow)
            .where(
                QuotaReservationRow.tenant_id == tenant_id,
                QuotaReservationRow.reservation_id == reservation_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NotFoundError(f"quota reservation not found: {reservation_id}")
        return row, self._reservation(row)

    async def commit(
        self,
        tenant_id: str,
        reservation_id: str,
        *,
        amount: int,
        window_key: str,
        ledger: UsageLedgerEntry,
    ) -> ResourceReservation:
        async with self._sessions() as session:
            row, reservation = await self._active_reservation(session, tenant_id, reservation_id)
            if reservation.state is ReservationState.COMMITTED:
                return reservation
            if reservation.state is not ReservationState.ACTIVE:
                raise ConflictError("quota reservation is not active")
            if amount < 0:
                raise ValueError("committed amount must not be negative")
            for constraint in sorted(reservation.constraints, key=lambda item: item.scope_key):
                counter = await self._locked_counter(
                    session,
                    tenant_id=tenant_id,
                    scope_key=constraint.scope_key,
                    resource=reservation.resource,
                    window_key=window_key,
                    limit=constraint.limit,
                )
                counter.reserved -= reservation.amount
                counter.committed += amount
                counter.updated_at = ledger.occurred_at
            committed = reservation.model_copy(
                update={
                    "state": ReservationState.COMMITTED,
                    "completed_at": ledger.occurred_at,
                }
            )
            row.state = committed.state.value
            row.payload = committed.model_dump(mode="json", by_alias=True)
            session.add(
                UsageLedgerRow(
                    tenant_id=ledger.tenant_id,
                    entry_id=ledger.entry_id,
                    reservation_id=ledger.reservation_id,
                    resource=ledger.resource.value,
                    amount=ledger.amount,
                    cost_state=ledger.cost_state.value,
                    occurred_at=ledger.occurred_at,
                    payload=ledger.model_dump(mode="json", by_alias=True),
                )
            )
            await session.commit()
            return committed

    async def release(
        self,
        tenant_id: str,
        reservation_id: str,
        *,
        state: ReservationState,
        window_key: str,
    ) -> ResourceReservation:
        async with self._sessions() as session:
            row, reservation = await self._active_reservation(session, tenant_id, reservation_id)
            if reservation.state is not ReservationState.ACTIVE:
                return reservation
            for constraint in sorted(reservation.constraints, key=lambda item: item.scope_key):
                counter = await self._locked_counter(
                    session,
                    tenant_id=tenant_id,
                    scope_key=constraint.scope_key,
                    resource=reservation.resource,
                    window_key=window_key,
                    limit=constraint.limit,
                )
                counter.reserved -= reservation.amount
                counter.updated_at = datetime.now(UTC)
            released = reservation.model_copy(
                update={"state": state, "completed_at": datetime.now(UTC)}
            )
            row.state = released.state.value
            row.payload = released.model_dump(mode="json", by_alias=True)
            await session.commit()
            return released

    async def add_ledger(self, entry: UsageLedgerEntry) -> None:
        async with self._sessions() as session:
            await session.execute(
                pg_insert(UsageLedgerRow)
                .values(
                    tenant_id=entry.tenant_id,
                    entry_id=entry.entry_id,
                    reservation_id=entry.reservation_id,
                    resource=entry.resource.value,
                    amount=entry.amount,
                    cost_state=entry.cost_state.value,
                    occurred_at=entry.occurred_at,
                    payload=entry.model_dump(mode="json", by_alias=True),
                )
                .on_conflict_do_nothing()
            )
            await session.commit()

    async def list_counters(self, tenant_id: str) -> Sequence[QuotaCounter]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(QuotaCounterRow).where(QuotaCounterRow.tenant_id == tenant_id)
                )
            ).all()
            return tuple(
                QuotaCounter(
                    tenantId=row.tenant_id,
                    scopeKey=row.scope_key,
                    resource=QuotaResource(row.resource),
                    windowKey=row.window_key,
                    reserved=row.reserved,
                    committed=row.committed,
                    limit=row.limit_value,
                )
                for row in rows
            )

    async def list_active_reservations(self, tenant_id: str) -> Sequence[ResourceReservation]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(QuotaReservationRow).where(
                        QuotaReservationRow.tenant_id == tenant_id,
                        QuotaReservationRow.state == ReservationState.ACTIVE.value,
                    )
                )
            ).all()
            return tuple(self._reservation(row) for row in rows)

    async def list_expired_active(
        self, now: datetime, *, limit: int
    ) -> Sequence[ResourceReservation]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(QuotaReservationRow)
                    .where(
                        QuotaReservationRow.state == ReservationState.ACTIVE.value,
                        QuotaReservationRow.expires_at <= now,
                    )
                    .order_by(QuotaReservationRow.expires_at)
                    .limit(limit)
                )
            ).all()
            return tuple(self._reservation(row) for row in rows)

    async def list_ledger(self, tenant_id: str) -> Sequence[UsageLedgerEntry]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(UsageLedgerRow).where(UsageLedgerRow.tenant_id == tenant_id)
                )
            ).all()
            return tuple(UsageLedgerEntry.model_validate(row.payload) for row in rows)
