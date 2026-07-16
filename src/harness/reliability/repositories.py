from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from harness.reliability.models import (
    CapacitySnapshot,
    IncidentStatus,
    ReaperAction,
    ReliabilityIncident,
)


class ReliabilityRepository(Protocol):
    async def upsert_incident(
        self, incident: ReliabilityIncident
    ) -> ReliabilityIncident: ...

    async def get_incident_by_fingerprint(
        self, tenant_id: str, fingerprint: str
    ) -> ReliabilityIncident | None: ...

    async def list_incidents(
        self,
        tenant_id: str,
        *,
        status: IncidentStatus | None,
        limit: int,
    ) -> Sequence[ReliabilityIncident]: ...

    async def list_recovery_incidents(
        self, *, kind: str, limit: int
    ) -> Sequence[ReliabilityIncident]: ...

    async def try_claim_incident(
        self,
        tenant_id: str,
        fingerprint: str,
        *,
        owner: str,
        claimed_at: datetime,
        lease_expires_at: datetime,
    ) -> ReliabilityIncident | None: ...

    async def add_reaper_action(self, action: ReaperAction) -> None: ...

    async def list_reaper_actions(
        self, tenant_id: str, *, limit: int
    ) -> Sequence[ReaperAction]: ...

    async def save_capacity(self, snapshot: CapacitySnapshot) -> None: ...

    async def latest_capacity(self, tenant_id: str) -> CapacitySnapshot | None: ...


class InMemoryReliabilityRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._incidents: dict[tuple[str, str], ReliabilityIncident] = {}
        self._fingerprints: dict[tuple[str, str], str] = {}
        self._actions: dict[str, ReaperAction] = {}
        self._capacities: dict[tuple[str, str], CapacitySnapshot] = {}

    async def upsert_incident(
        self, incident: ReliabilityIncident
    ) -> ReliabilityIncident:
        async with self._lock:
            fingerprint = (incident.tenant_id, incident.fingerprint)
            existing_id = self._fingerprints.get(fingerprint)
            if existing_id is not None:
                key = (incident.tenant_id, existing_id)
                current = self._incidents[key]
                updated = incident.model_copy(
                    update={
                        "incident_id": current.incident_id,
                        "opened_at": current.opened_at,
                    }
                )
                self._incidents[key] = updated
                return updated
            key = (incident.tenant_id, incident.incident_id)
            self._incidents[key] = incident
            self._fingerprints[fingerprint] = incident.incident_id
            return incident

    async def get_incident_by_fingerprint(
        self, tenant_id: str, fingerprint: str
    ) -> ReliabilityIncident | None:
        incident_id = self._fingerprints.get((tenant_id, fingerprint))
        return self._incidents.get((tenant_id, incident_id)) if incident_id else None

    async def list_incidents(
        self,
        tenant_id: str,
        *,
        status: IncidentStatus | None,
        limit: int,
    ) -> Sequence[ReliabilityIncident]:
        values = [
            incident
            for (stored_tenant, _), incident in self._incidents.items()
            if stored_tenant == tenant_id and (status is None or incident.status is status)
        ]
        return tuple(
            sorted(values, key=lambda item: item.updated_at, reverse=True)[:limit]
        )

    async def list_recovery_incidents(
        self, *, kind: str, limit: int
    ) -> Sequence[ReliabilityIncident]:
        values = [
            incident
            for incident in self._incidents.values()
            if incident.status is IncidentStatus.OPEN and incident.kind == kind
        ]
        return tuple(
            sorted(values, key=lambda item: item.updated_at)[:limit]
        )

    async def try_claim_incident(
        self,
        tenant_id: str,
        fingerprint: str,
        *,
        owner: str,
        claimed_at: datetime,
        lease_expires_at: datetime,
    ) -> ReliabilityIncident | None:
        async with self._lock:
            incident_id = self._fingerprints.get((tenant_id, fingerprint))
            if incident_id is None:
                return None
            key = (tenant_id, incident_id)
            current = self._incidents[key]
            if current.status is not IncidentStatus.OPEN:
                return None
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
            self._incidents[key] = claimed
            return claimed

    async def add_reaper_action(self, action: ReaperAction) -> None:
        async with self._lock:
            self._actions.setdefault(action.action_id, action)

    async def list_reaper_actions(
        self, tenant_id: str, *, limit: int
    ) -> Sequence[ReaperAction]:
        values = [
            action
            for action in self._actions.values()
            if action.tenant_id in {tenant_id, "platform"}
        ]
        return tuple(
            sorted(values, key=lambda item: item.occurred_at, reverse=True)[:limit]
        )

    async def save_capacity(self, snapshot: CapacitySnapshot) -> None:
        async with self._lock:
            self._capacities.setdefault(
                (snapshot.tenant_id, snapshot.snapshot_id), snapshot
            )

    async def latest_capacity(self, tenant_id: str) -> CapacitySnapshot | None:
        values = [
            snapshot
            for (stored_tenant, _), snapshot in self._capacities.items()
            if stored_tenant == tenant_id
        ]
        if not values:
            return None
        return max(values, key=lambda item: item.captured_at)
