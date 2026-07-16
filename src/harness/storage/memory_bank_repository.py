from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError

from harness.core.errors import ConflictError, NotFoundError
from harness.memory_bank.models import (
    MemoryConsent,
    MemoryEntry,
    MemoryRetention,
    MemoryStatus,
)
from harness.storage.database import SessionFactory
from harness.storage.models import MemoryConsentRow, MemoryEntryRow, MemoryRetentionRow


class PostgresMemoryBankRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def add_entry(self, entry: MemoryEntry) -> None:
        async with self._sessions() as db:
            db.add(
                MemoryEntryRow(
                    tenant_id=entry.tenant_id,
                    user_id=entry.user_id,
                    entry_id=entry.entry_id,
                    agent_name=entry.agent_name,
                    status=entry.status.value,
                    version=entry.version,
                    updated_at=entry.updated_at,
                    expires_at=entry.expires_at,
                    payload=entry.model_dump(mode="json", by_alias=True),
                )
            )
            try:
                await db.commit()
            except IntegrityError as error:
                await db.rollback()
                raise ConflictError(f"memory entry already exists: {entry.entry_id}") from error

    async def get_entry(
        self, tenant_id: str, user_id: str, entry_id: str
    ) -> MemoryEntry:
        async with self._sessions() as db:
            row = await db.get(MemoryEntryRow, (tenant_id, user_id, entry_id))
            if row is None:
                raise NotFoundError(f"memory entry not found: {entry_id}")
            return MemoryEntry.model_validate(row.payload)

    async def list_entries(
        self,
        tenant_id: str,
        user_id: str,
        *,
        agent_name: str | None,
        statuses: frozenset[MemoryStatus] | None,
        limit: int,
    ) -> Sequence[MemoryEntry]:
        statement = select(MemoryEntryRow).where(
            MemoryEntryRow.tenant_id == tenant_id,
            MemoryEntryRow.user_id == user_id,
        )
        if agent_name is not None:
            statement = statement.where(MemoryEntryRow.agent_name == agent_name)
        if statuses is not None:
            statement = statement.where(
                MemoryEntryRow.status.in_(tuple(status.value for status in statuses))
            )
        statement = statement.order_by(
            MemoryEntryRow.updated_at.desc(), MemoryEntryRow.entry_id.desc()
        ).limit(limit)
        async with self._sessions() as db:
            rows = (await db.scalars(statement)).all()
        return tuple(MemoryEntry.model_validate(row.payload) for row in rows)

    async def compare_and_set_entry(
        self, expected_version: int, updated: MemoryEntry
    ) -> bool:
        if updated.version != expected_version + 1:
            raise ConflictError("memory entry version must increment by one")
        statement = (
            update(MemoryEntryRow)
            .where(
                MemoryEntryRow.tenant_id == updated.tenant_id,
                MemoryEntryRow.user_id == updated.user_id,
                MemoryEntryRow.entry_id == updated.entry_id,
                MemoryEntryRow.version == expected_version,
            )
            .values(
                status=updated.status.value,
                version=updated.version,
                updated_at=updated.updated_at,
                expires_at=updated.expires_at,
                payload=updated.model_dump(mode="json", by_alias=True),
            )
        )
        async with self._sessions() as db:
            result = await db.execute(statement)
            await db.commit()
            return bool(cast(CursorResult[Any], result).rowcount)

    async def list_expired(self, now: datetime, *, limit: int) -> Sequence[MemoryEntry]:
        statement = (
            select(MemoryEntryRow)
            .where(
                MemoryEntryRow.status == MemoryStatus.ACTIVE.value,
                MemoryEntryRow.expires_at.is_not(None),
                MemoryEntryRow.expires_at <= now,
            )
            .order_by(MemoryEntryRow.expires_at)
            .limit(limit)
        )
        async with self._sessions() as db:
            rows = (await db.scalars(statement)).all()
        return tuple(MemoryEntry.model_validate(row.payload) for row in rows)

    async def get_consent(
        self, tenant_id: str, user_id: str, agent_name: str
    ) -> MemoryConsent | None:
        async with self._sessions() as db:
            row = await db.get(MemoryConsentRow, (tenant_id, user_id, agent_name))
            return None if row is None else MemoryConsent.model_validate(row.payload)

    async def put_consent(
        self, expected_version: int, consent: MemoryConsent
    ) -> bool:
        return await self._put_policy(
            MemoryConsentRow, expected_version, consent.version, consent
        )

    async def get_retention(
        self, tenant_id: str, user_id: str, agent_name: str
    ) -> MemoryRetention | None:
        async with self._sessions() as db:
            row = await db.get(MemoryRetentionRow, (tenant_id, user_id, agent_name))
            return None if row is None else MemoryRetention.model_validate(row.payload)

    async def put_retention(
        self, expected_version: int, retention: MemoryRetention
    ) -> bool:
        return await self._put_policy(
            MemoryRetentionRow, expected_version, retention.version, retention
        )

    async def _put_policy(
        self,
        row_type: type[MemoryConsentRow] | type[MemoryRetentionRow],
        expected_version: int,
        new_version: int,
        value: MemoryConsent | MemoryRetention,
    ) -> bool:
        if new_version != expected_version + 1:
            return False
        key = (value.tenant_id, value.user_id, value.agent_name)
        async with self._sessions() as db:
            if expected_version == 0:
                db.add(
                    row_type(
                        tenant_id=value.tenant_id,
                        user_id=value.user_id,
                        agent_name=value.agent_name,
                        version=new_version,
                        payload=value.model_dump(mode="json", by_alias=True),
                    )
                )
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    return False
                return True
            statement = (
                update(row_type)
                .where(
                    row_type.tenant_id == key[0],
                    row_type.user_id == key[1],
                    row_type.agent_name == key[2],
                    row_type.version == expected_version,
                )
                .values(
                    version=new_version,
                    payload=value.model_dump(mode="json", by_alias=True),
                )
            )
            result = await db.execute(statement)
            await db.commit()
            return bool(cast(CursorResult[Any], result).rowcount)
