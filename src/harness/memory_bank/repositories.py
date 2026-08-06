from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.memory_bank.models import (
    MemoryConsent,
    MemoryEntry,
    MemoryRetention,
    MemoryStatus,
)


class MemoryBankRepository(Protocol):
    async def add_entry(self, entry: MemoryEntry) -> None: ...

    async def get_entry(
        self, tenant_id: str, user_id: str, entry_id: str
    ) -> MemoryEntry: ...

    async def list_entries(
        self,
        tenant_id: str,
        user_id: str,
        *,
        agent_name: str | None,
        statuses: frozenset[MemoryStatus] | None,
        limit: int,
    ) -> Sequence[MemoryEntry]: ...

    async def compare_and_set_entry(
        self, expected_version: int, updated: MemoryEntry
    ) -> bool: ...

    async def list_expired(self, now: datetime, *, limit: int) -> Sequence[MemoryEntry]: ...

    async def get_consent(
        self, tenant_id: str, user_id: str, agent_name: str
    ) -> MemoryConsent | None: ...

    async def put_consent(
        self, expected_version: int, consent: MemoryConsent
    ) -> bool: ...

    async def get_retention(
        self, tenant_id: str, user_id: str, agent_name: str
    ) -> MemoryRetention | None: ...

    async def put_retention(
        self, expected_version: int, retention: MemoryRetention
    ) -> bool: ...


class InMemoryMemoryBankRepository:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], MemoryEntry] = {}
        self._consents: dict[tuple[str, str, str], MemoryConsent] = {}
        self._retentions: dict[tuple[str, str, str], MemoryRetention] = {}
        self._lock = asyncio.Lock()

    async def add_entry(self, entry: MemoryEntry) -> None:
        key = (entry.tenant_id, entry.user_id, entry.entry_id)
        async with self._lock:
            if key in self._entries:
                raise ConflictError(f"memory entry already exists: {entry.entry_id}")
            self._entries[key] = entry

    async def get_entry(
        self, tenant_id: str, user_id: str, entry_id: str
    ) -> MemoryEntry:
        try:
            return self._entries[(tenant_id, user_id, entry_id)]
        except KeyError as error:
            raise NotFoundError(f"memory entry not found: {entry_id}") from error

    async def list_entries(
        self,
        tenant_id: str,
        user_id: str,
        *,
        agent_name: str | None,
        statuses: frozenset[MemoryStatus] | None,
        limit: int,
    ) -> Sequence[MemoryEntry]:
        values = [
            entry
            for (stored_tenant, stored_user, _), entry in self._entries.items()
            if stored_tenant == tenant_id
            and stored_user == user_id
            and (agent_name is None or entry.agent_name == agent_name)
            and (statuses is None or entry.status in statuses)
        ]
        return tuple(
            sorted(values, key=lambda item: (item.updated_at, item.entry_id), reverse=True)[
                :limit
            ]
        )

    async def compare_and_set_entry(
        self, expected_version: int, updated: MemoryEntry
    ) -> bool:
        if updated.version != expected_version + 1:
            raise ConflictError("memory entry version must increment by one")
        key = (updated.tenant_id, updated.user_id, updated.entry_id)
        async with self._lock:
            current = self._entries.get(key)
            if current is None:
                raise NotFoundError(f"memory entry not found: {updated.entry_id}")
            if current.version != expected_version:
                return False
            self._entries[key] = updated
            return True

    async def list_expired(self, now: datetime, *, limit: int) -> Sequence[MemoryEntry]:
        values = [
            entry
            for entry in self._entries.values()
            if entry.status is MemoryStatus.ACTIVE
            and entry.expires_at is not None
            and entry.expires_at <= now
        ]

        def expiry(item: MemoryEntry) -> datetime:
            assert item.expires_at is not None
            return item.expires_at

        return tuple(sorted(values, key=expiry)[:limit])

    async def get_consent(
        self, tenant_id: str, user_id: str, agent_name: str
    ) -> MemoryConsent | None:
        return self._consents.get((tenant_id, user_id, agent_name))

    async def put_consent(
        self, expected_version: int, consent: MemoryConsent
    ) -> bool:
        key = (consent.tenant_id, consent.user_id, consent.agent_name)
        async with self._lock:
            current = self._consents.get(key)
            if current is None:
                if expected_version != 0 or consent.version != 1:
                    return False
            elif current.version != expected_version or consent.version != expected_version + 1:
                return False
            self._consents[key] = consent
            return True

    async def get_retention(
        self, tenant_id: str, user_id: str, agent_name: str
    ) -> MemoryRetention | None:
        return self._retentions.get((tenant_id, user_id, agent_name))

    async def put_retention(
        self, expected_version: int, retention: MemoryRetention
    ) -> bool:
        key = (retention.tenant_id, retention.user_id, retention.agent_name)
        async with self._lock:
            current = self._retentions.get(key)
            if current is None:
                if expected_version != 0 or retention.version != 1:
                    return False
            elif current.version != expected_version or retention.version != expected_version + 1:
                return False
            self._retentions[key] = retention
            return True
