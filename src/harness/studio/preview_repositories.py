"""Preview Deployment persistence ports and in-memory adapter."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.studio.preview_models import PreviewDeployment, PreviewStatus


class PreviewRepository(Protocol):
    async def add(self, preview: PreviewDeployment) -> None: ...

    async def get(self, tenant_id: str, preview_id: str) -> PreviewDeployment: ...

    async def find_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> PreviewDeployment | None: ...

    async def list_for_tenant(self, tenant_id: str) -> list[PreviewDeployment]: ...

    async def compare_and_set(
        self, expected_status: PreviewStatus, updated: PreviewDeployment
    ) -> bool: ...

    async def list_expired_active(
        self, expires_at_or_before: datetime, *, limit: int
    ) -> list[PreviewDeployment]: ...


class InMemoryPreviewRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], PreviewDeployment] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    async def add(self, preview: PreviewDeployment) -> None:
        key = (preview.tenant_id, preview.preview_id)
        idem = (preview.tenant_id, preview.idempotency_key)
        async with self._lock:
            if key in self._items or idem in self._idempotency:
                raise ConflictError("Preview Deployment already exists")
            self._items[key] = preview
            self._idempotency[idem] = preview.preview_id

    async def get(self, tenant_id: str, preview_id: str) -> PreviewDeployment:
        try:
            return self._items[(tenant_id, preview_id)]
        except KeyError as error:
            raise NotFoundError(f"Preview Deployment not found: {preview_id}") from error

    async def find_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> PreviewDeployment | None:
        preview_id = self._idempotency.get((tenant_id, idempotency_key))
        return None if preview_id is None else self._items[(tenant_id, preview_id)]

    async def list_for_tenant(self, tenant_id: str) -> list[PreviewDeployment]:
        return sorted(
            (
                preview
                for (stored_tenant, _preview_id), preview in self._items.items()
                if stored_tenant == tenant_id
            ),
            key=lambda item: (item.created_at, item.preview_id),
            reverse=True,
        )

    async def compare_and_set(
        self, expected_status: PreviewStatus, updated: PreviewDeployment
    ) -> bool:
        key = (updated.tenant_id, updated.preview_id)
        async with self._lock:
            current = self._items.get(key)
            if current is None or current.status is not expected_status:
                return False
            if updated.fencing_token != current.fencing_token + 1:
                raise ConflictError("Preview fencing token must increment once")
            self._items[key] = updated
            return True

    async def list_expired_active(
        self, expires_at_or_before: datetime, *, limit: int
    ) -> list[PreviewDeployment]:
        if limit < 1:
            raise ValueError("Preview reaper limit must be positive")
        return sorted(
            (
                item
                for item in self._items.values()
                if not item.status.is_terminal
                and item.expires_at <= expires_at_or_before
            ),
            key=lambda item: (item.expires_at, item.preview_id),
        )[:limit]
