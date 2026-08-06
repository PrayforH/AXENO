"""Capability Catalog persistence port and deterministic memory adapter."""

import asyncio
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.studio.models import CapabilityCatalogRecord


class CapabilityCatalogRepository(Protocol):
    async def seed(self, record: CapabilityCatalogRecord) -> CapabilityCatalogRecord: ...

    async def get(self, tenant_id: str) -> CapabilityCatalogRecord: ...

    async def replace(
        self, expected_revision: int, record: CapabilityCatalogRecord
    ) -> None: ...


class InMemoryCapabilityCatalogRepository:
    def __init__(self) -> None:
        self._items: dict[str, CapabilityCatalogRecord] = {}
        self._lock = asyncio.Lock()

    async def seed(self, record: CapabilityCatalogRecord) -> CapabilityCatalogRecord:
        async with self._lock:
            current = self._items.get(record.tenant_id)
            if current is not None:
                return current
            self._items[record.tenant_id] = record
            return record

    async def get(self, tenant_id: str) -> CapabilityCatalogRecord:
        try:
            return self._items[tenant_id]
        except KeyError as error:
            raise NotFoundError(f"Capability catalog not found: {tenant_id}") from error

    async def replace(
        self, expected_revision: int, record: CapabilityCatalogRecord
    ) -> None:
        async with self._lock:
            current = self._items.get(record.tenant_id)
            if current is None:
                raise NotFoundError(
                    f"Capability catalog not found: {record.tenant_id}"
                )
            if current.revision != expected_revision:
                raise ConflictError(
                    "Capability catalog revision changed: "
                    f"expected={expected_revision} actual={current.revision}"
                )
            if record.revision != expected_revision + 1:
                raise ConflictError("Capability catalog revision must increment once")
            self._items[record.tenant_id] = record
