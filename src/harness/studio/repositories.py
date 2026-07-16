"""Draft persistence ports and a deterministic in-memory implementation."""

from __future__ import annotations

import asyncio
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.studio.models import AgentDraft


class AgentDraftRepository(Protocol):
    async def add(self, draft: AgentDraft) -> None: ...

    async def get(self, tenant_id: str, draft_id: str) -> AgentDraft: ...

    async def list_for_tenant(self, tenant_id: str) -> list[AgentDraft]: ...

    async def replace(self, expected_revision: int, draft: AgentDraft) -> None: ...


class InMemoryAgentDraftRepository:
    """Optimistic, tenant-scoped draft storage used by tests and local previews."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], AgentDraft] = {}
        self._lock = asyncio.Lock()

    async def add(self, draft: AgentDraft) -> None:
        key = (draft.tenant_id, draft.draft_id)
        async with self._lock:
            if key in self._items:
                raise ConflictError(f"Agent draft already exists: {draft.draft_id}")
            self._items[key] = draft

    async def get(self, tenant_id: str, draft_id: str) -> AgentDraft:
        try:
            return self._items[(tenant_id, draft_id)]
        except KeyError as error:
            raise NotFoundError(f"Agent draft not found: {draft_id}") from error

    async def list_for_tenant(self, tenant_id: str) -> list[AgentDraft]:
        return sorted(
            (
                draft
                for (stored_tenant, _draft_id), draft in self._items.items()
                if stored_tenant == tenant_id
            ),
            key=lambda draft: (draft.updated_at, draft.draft_id),
            reverse=True,
        )

    async def replace(self, expected_revision: int, draft: AgentDraft) -> None:
        key = (draft.tenant_id, draft.draft_id)
        async with self._lock:
            current = self._items.get(key)
            if current is None:
                raise NotFoundError(f"Agent draft not found: {draft.draft_id}")
            if current.revision != expected_revision:
                raise ConflictError(
                    "Agent draft revision changed: "
                    f"expected={expected_revision} actual={current.revision}"
                )
            if draft.revision != expected_revision + 1:
                raise ConflictError("Agent draft replacement must increment revision once")
            self._items[key] = draft
