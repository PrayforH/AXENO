from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from harness.reliability.models import (
    CapacitySnapshot,
    IncidentStatus,
    ReaperAction,
    ReliabilityIncident,
)
from harness.storage.database import SessionFactory
from harness.storage.models import (
    CapacitySnapshotRow,
    ReaperActionRow,
    ReliabilityIncidentRow,
)


class PostgresReliabilityRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def upsert_incident(
        self, incident: ReliabilityIncident
    ) -> ReliabilityIncident:
        async with self._sessions() as db:
            await db.execute(
                insert(ReliabilityIncidentRow)
                .values(
                    tenant_id=incident.tenant_id,
                    incident_id=incident.incident_id,
                    fingerprint=incident.fingerprint,
                    kind=incident.kind,
                    status=incident.status.value,
                    updated_at=incident.updated_at,
                    payload=incident.model_dump(mode="json", by_alias=True),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        ReliabilityIncidentRow.tenant_id,
                        ReliabilityIncidentRow.fingerprint,
                    ]
                )
            )
            row = await db.scalar(
                select(ReliabilityIncidentRow)
                .where(
                    ReliabilityIncidentRow.tenant_id == incident.tenant_id,
                    ReliabilityIncidentRow.fingerprint == incident.fingerprint,
                )
                .with_for_update()
            )
            if row is None:  # pragma: no cover - protected by INSERT ... ON CONFLICT
                raise RuntimeError("incident upsert did not produce a durable row")
            current = ReliabilityIncident.model_validate(row.payload)
            stored = incident.model_copy(
                update={
                    "incident_id": current.incident_id,
                    "opened_at": current.opened_at,
                }
            )
            row.status = stored.status.value
            row.kind = stored.kind
            row.updated_at = stored.updated_at
            row.payload = stored.model_dump(mode="json", by_alias=True)
            await db.commit()
            return stored

    async def get_incident_by_fingerprint(
        self, tenant_id: str, fingerprint: str
    ) -> ReliabilityIncident | None:
        async with self._sessions() as db:
            row = await db.scalar(
                select(ReliabilityIncidentRow).where(
                    ReliabilityIncidentRow.tenant_id == tenant_id,
                    ReliabilityIncidentRow.fingerprint == fingerprint,
                )
            )
            return ReliabilityIncident.model_validate(row.payload) if row else None

    async def list_incidents(
        self,
        tenant_id: str,
        *,
        status: IncidentStatus | None,
        limit: int,
    ) -> Sequence[ReliabilityIncident]:
        statement = select(ReliabilityIncidentRow).where(
            ReliabilityIncidentRow.tenant_id.in_((tenant_id, "platform"))
        )
        if status is not None:
            statement = statement.where(
                ReliabilityIncidentRow.status == status.value
            )
        async with self._sessions() as db:
            rows = (
                await db.scalars(
                    statement.order_by(ReliabilityIncidentRow.updated_at.desc()).limit(
                        limit
                    )
                )
            ).all()
            return tuple(ReliabilityIncident.model_validate(row.payload) for row in rows)

    async def list_recovery_incidents(
        self, *, kind: str, limit: int
    ) -> Sequence[ReliabilityIncident]:
        async with self._sessions() as db:
            rows = (
                await db.scalars(
                    select(ReliabilityIncidentRow)
                    .where(
                        ReliabilityIncidentRow.status == IncidentStatus.OPEN.value,
                        ReliabilityIncidentRow.kind == kind,
                    )
                    .order_by(ReliabilityIncidentRow.updated_at)
                    .limit(limit)
                )
            ).all()
        return tuple(ReliabilityIncident.model_validate(row.payload) for row in rows)

    async def try_claim_incident(
        self,
        tenant_id: str,
        fingerprint: str,
        *,
        owner: str,
        claimed_at: datetime,
        lease_expires_at: datetime,
    ) -> ReliabilityIncident | None:
        async with self._sessions() as db:
            row = await db.scalar(
                select(ReliabilityIncidentRow)
                .where(
                    ReliabilityIncidentRow.tenant_id == tenant_id,
                    ReliabilityIncidentRow.fingerprint == fingerprint,
                )
                .with_for_update()
            )
            if row is None or row.status != IncidentStatus.OPEN.value:
                return None
            current = ReliabilityIncident.model_validate(row.payload)
            if (
                current.recovery_lease_expires_at is not None
                and current.recovery_lease_expires_at > claimed_at
            ):
                return None
            claimed = current.model_copy(
                update={
                    "recovery_owner": owner,
                    "recovery_lease_expires_at": lease_expires_at,
                    "recovery_attempts": current.recovery_attempts + 1,
                    "updated_at": claimed_at,
                }
            )
            row.updated_at = claimed_at
            row.payload = claimed.model_dump(mode="json", by_alias=True)
            await db.commit()
            return claimed

    async def add_reaper_action(self, action: ReaperAction) -> None:
        async with self._sessions() as db:
            if await db.get(ReaperActionRow, action.action_id) is not None:
                return
            db.add(
                ReaperActionRow(
                    action_id=action.action_id,
                    tenant_id=action.tenant_id,
                    reaper=action.reaper,
                    resource_type=action.resource_type,
                    resource_id=action.resource_id,
                    outcome=action.outcome.value,
                    occurred_at=action.occurred_at,
                    payload=action.model_dump(mode="json", by_alias=True),
                )
            )
            await db.commit()

    async def list_reaper_actions(
        self, tenant_id: str, *, limit: int
    ) -> Sequence[ReaperAction]:
        async with self._sessions() as db:
            rows = (
                await db.scalars(
                    select(ReaperActionRow)
                    .where(ReaperActionRow.tenant_id.in_((tenant_id, "platform")))
                    .order_by(ReaperActionRow.occurred_at.desc())
                    .limit(limit)
                )
            ).all()
            return tuple(ReaperAction.model_validate(row.payload) for row in rows)

    async def save_capacity(self, snapshot: CapacitySnapshot) -> None:
        async with self._sessions() as db:
            if (
                await db.get(
                    CapacitySnapshotRow,
                    (snapshot.tenant_id, snapshot.snapshot_id),
                )
                is None
            ):
                db.add(
                    CapacitySnapshotRow(
                        tenant_id=snapshot.tenant_id,
                        snapshot_id=snapshot.snapshot_id,
                        captured_at=snapshot.captured_at,
                        payload=snapshot.model_dump(mode="json", by_alias=True),
                    )
                )
                await db.commit()

    async def latest_capacity(self, tenant_id: str) -> CapacitySnapshot | None:
        async with self._sessions() as db:
            row = await db.scalar(
                select(CapacitySnapshotRow)
                .where(CapacitySnapshotRow.tenant_id == tenant_id)
                .order_by(CapacitySnapshotRow.captured_at.desc())
                .limit(1)
            )
            return CapacitySnapshot.model_validate(row.payload) if row else None
