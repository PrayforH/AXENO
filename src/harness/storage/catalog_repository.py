"""PostgreSQL adapter for tenant-scoped capability catalogs."""

from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError

from harness.core.errors import ConflictError, NotFoundError
from harness.storage.database import SessionFactory
from harness.storage.models import CapabilityCatalogRow
from harness.studio.models import CapabilityCatalogRecord


class PostgresCapabilityCatalogRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def seed(self, record: CapabilityCatalogRecord) -> CapabilityCatalogRecord:
        async with self._sessions() as session:
            session.add(
                CapabilityCatalogRow(
                    tenant_id=record.tenant_id,
                    revision=record.revision,
                    updated_by=record.updated_by,
                    updated_at=record.updated_at,
                    payload=record.model_dump(mode="json", by_alias=True),
                )
            )
            try:
                await session.commit()
                return record
            except IntegrityError:
                await session.rollback()
        return await self.get(record.tenant_id)

    async def get(self, tenant_id: str) -> CapabilityCatalogRecord:
        async with self._sessions() as session:
            row = await session.get(CapabilityCatalogRow, tenant_id)
            if row is None:
                raise NotFoundError(f"Capability catalog not found: {tenant_id}")
            record = CapabilityCatalogRecord.model_validate(row.payload)
            if record.tenant_id != row.tenant_id or record.revision != row.revision:
                raise ValueError(f"Corrupt Capability Catalog envelope: {tenant_id}")
            return record

    async def replace(
        self, expected_revision: int, record: CapabilityCatalogRecord
    ) -> None:
        if record.revision != expected_revision + 1:
            raise ConflictError("Capability catalog revision must increment once")
        statement = (
            update(CapabilityCatalogRow)
            .where(
                CapabilityCatalogRow.tenant_id == record.tenant_id,
                CapabilityCatalogRow.revision == expected_revision,
            )
            .values(
                revision=record.revision,
                updated_by=record.updated_by,
                updated_at=record.updated_at,
                payload=record.model_dump(mode="json", by_alias=True),
            )
        )
        async with self._sessions() as session:
            result = await session.execute(statement)
            if cast(CursorResult[Any], result).rowcount:
                await session.commit()
                return
            actual = await session.scalar(
                select(CapabilityCatalogRow.revision).where(
                    CapabilityCatalogRow.tenant_id == record.tenant_id
                )
            )
            await session.rollback()
            if actual is None:
                raise NotFoundError(
                    f"Capability catalog not found: {record.tenant_id}"
                )
            raise ConflictError(
                "Capability catalog revision changed: "
                f"expected={expected_revision} actual={actual}"
            )
