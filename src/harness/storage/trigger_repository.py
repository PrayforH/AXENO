"""PostgreSQL Agent Trigger repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError

from harness.core.errors import ConflictError, NotFoundError
from harness.storage.database import SessionFactory
from harness.storage.models import AgentTriggerRow
from harness.triggers.models import StoredAgentTrigger


def _payload(trigger: StoredAgentTrigger) -> dict[str, Any]:
    return trigger.model_dump(mode="json", by_alias=True)


def _trigger(row: AgentTriggerRow) -> StoredAgentTrigger:
    value = StoredAgentTrigger.model_validate(row.payload)
    if (
        value.trigger_id,
        value.tenant_id,
        value.agent_name,
        value.environment.value,
        value.enabled,
        value.revision,
        value.created_at,
        value.updated_at,
    ) != (
        row.trigger_id,
        row.tenant_id,
        row.agent_name,
        row.environment,
        row.enabled,
        row.revision,
        row.created_at,
        row.updated_at,
    ):
        raise ValueError("Corrupt Agent Trigger persistence envelope")
    return value


class PostgresAgentTriggerRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def add(self, trigger: StoredAgentTrigger) -> None:
        async with self._sessions() as session:
            session.add(
                AgentTriggerRow(
                    trigger_id=trigger.trigger_id,
                    tenant_id=trigger.tenant_id,
                    agent_name=trigger.agent_name,
                    environment=trigger.environment.value,
                    enabled=trigger.enabled,
                    revision=trigger.revision,
                    created_at=trigger.created_at,
                    updated_at=trigger.updated_at,
                    payload=_payload(trigger),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ConflictError(
                    f"Agent Trigger already exists: {trigger.trigger_id}"
                ) from error

    async def get(self, tenant_id: str, trigger_id: str) -> StoredAgentTrigger:
        trigger = await self.get_public(trigger_id)
        if trigger.tenant_id != tenant_id:
            raise NotFoundError(f"Agent Trigger not found: {trigger_id}")
        return trigger

    async def get_public(self, trigger_id: str) -> StoredAgentTrigger:
        async with self._sessions() as session:
            row = await session.get(AgentTriggerRow, trigger_id)
            if row is None:
                raise NotFoundError(f"Agent Trigger not found: {trigger_id}")
            return _trigger(row)

    async def list_for_agent(
        self, tenant_id: str, agent_name: str
    ) -> list[StoredAgentTrigger]:
        statement = (
            select(AgentTriggerRow)
            .where(
                AgentTriggerRow.tenant_id == tenant_id,
                AgentTriggerRow.agent_name == agent_name,
            )
            .order_by(
                AgentTriggerRow.created_at.desc(),
                AgentTriggerRow.trigger_id.desc(),
            )
        )
        async with self._sessions() as session:
            return [_trigger(row) for row in (await session.scalars(statement)).all()]

    async def replace(
        self, expected_revision: int, trigger: StoredAgentTrigger
    ) -> None:
        statement = (
            update(AgentTriggerRow)
            .where(
                AgentTriggerRow.trigger_id == trigger.trigger_id,
                AgentTriggerRow.tenant_id == trigger.tenant_id,
                AgentTriggerRow.revision == expected_revision,
            )
            .values(
                enabled=trigger.enabled,
                revision=trigger.revision,
                updated_at=trigger.updated_at,
                payload=_payload(trigger),
            )
        )
        async with self._sessions() as session:
            result = await session.execute(statement)
            changed = bool(cast(CursorResult[Any], result).rowcount)
            await (session.commit() if changed else session.rollback())
        if not changed:
            try:
                current = await self.get(trigger.tenant_id, trigger.trigger_id)
            except NotFoundError:
                raise
            raise ConflictError(
                "Agent Trigger revision changed: "
                f"expected={expected_revision} actual={current.revision}"
            )

    async def touch_invoked(
        self, trigger_id: str, invoked_at: datetime
    ) -> StoredAgentTrigger:
        async with self._sessions() as session:
            row = await session.get(AgentTriggerRow, trigger_id)
            if row is None:
                raise NotFoundError(f"Agent Trigger not found: {trigger_id}")
            current = _trigger(row)
            updated = current.model_copy(
                update={"last_invoked_at": invoked_at, "updated_at": invoked_at}
            )
            row.updated_at = invoked_at
            row.payload = _payload(updated)
            await session.commit()
            return updated
