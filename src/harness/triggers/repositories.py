"""Trigger persistence port and in-memory adapter."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.triggers.models import StoredAgentTrigger


class AgentTriggerRepository(Protocol):
    async def add(self, trigger: StoredAgentTrigger) -> None: ...
    async def get(self, tenant_id: str, trigger_id: str) -> StoredAgentTrigger: ...
    async def get_public(self, trigger_id: str) -> StoredAgentTrigger: ...
    async def list_for_agent(
        self, tenant_id: str, agent_name: str
    ) -> list[StoredAgentTrigger]: ...
    async def replace(
        self, expected_revision: int, trigger: StoredAgentTrigger
    ) -> None: ...
    async def touch_invoked(
        self, trigger_id: str, invoked_at: datetime
    ) -> StoredAgentTrigger: ...


class InMemoryAgentTriggerRepository:
    def __init__(self) -> None:
        self._items: dict[str, StoredAgentTrigger] = {}
        self._lock = asyncio.Lock()

    async def add(self, trigger: StoredAgentTrigger) -> None:
        async with self._lock:
            if trigger.trigger_id in self._items:
                raise ConflictError(f"Agent Trigger already exists: {trigger.trigger_id}")
            self._items[trigger.trigger_id] = trigger

    async def get(self, tenant_id: str, trigger_id: str) -> StoredAgentTrigger:
        trigger = await self.get_public(trigger_id)
        if trigger.tenant_id != tenant_id:
            raise NotFoundError(f"Agent Trigger not found: {trigger_id}")
        return trigger

    async def get_public(self, trigger_id: str) -> StoredAgentTrigger:
        try:
            return self._items[trigger_id]
        except KeyError as error:
            raise NotFoundError(f"Agent Trigger not found: {trigger_id}") from error

    async def list_for_agent(
        self, tenant_id: str, agent_name: str
    ) -> list[StoredAgentTrigger]:
        return sorted(
            (
                item
                for item in self._items.values()
                if item.tenant_id == tenant_id and item.agent_name == agent_name
            ),
            key=lambda item: (item.created_at, item.trigger_id),
            reverse=True,
        )

    async def replace(
        self, expected_revision: int, trigger: StoredAgentTrigger
    ) -> None:
        async with self._lock:
            current = self._items.get(trigger.trigger_id)
            if current is None or current.tenant_id != trigger.tenant_id:
                raise NotFoundError(f"Agent Trigger not found: {trigger.trigger_id}")
            if current.revision != expected_revision:
                raise ConflictError(
                    "Agent Trigger revision changed: "
                    f"expected={expected_revision} actual={current.revision}"
                )
            if trigger.revision != expected_revision + 1:
                raise ConflictError("Agent Trigger replacement must increment revision once")
            self._items[trigger.trigger_id] = trigger

    async def touch_invoked(
        self, trigger_id: str, invoked_at: datetime
    ) -> StoredAgentTrigger:
        async with self._lock:
            current = self._items.get(trigger_id)
            if current is None:
                raise NotFoundError(f"Agent Trigger not found: {trigger_id}")
            updated = current.model_copy(
                update={"last_invoked_at": invoked_at, "updated_at": invoked_at}
            )
            self._items[trigger_id] = updated
            return updated
