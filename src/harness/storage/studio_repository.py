"""PostgreSQL adapter for tenant-and-owner-scoped Agent Studio drafts."""

from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError

from harness.core.errors import ConflictError, NotFoundError
from harness.storage.database import SessionFactory
from harness.storage.models import AgentDraftRow
from harness.studio.models import AgentDraft, AgentDraftSummary

AGENT_DRAFT_SCHEMA_VERSION = 1


def _draft_payload(draft: AgentDraft) -> dict[str, Any]:
    return draft.model_dump(mode="json", by_alias=True)


def _load_draft(row: AgentDraftRow) -> AgentDraft:
    if row.schema_version != AGENT_DRAFT_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported Agent Draft schema version: "
            f"{row.schema_version}; expected={AGENT_DRAFT_SCHEMA_VERSION}"
        )
    draft = AgentDraft.model_validate(row.payload)
    if draft.agent_id is None and row.agent_id is not None:
        draft = draft.model_copy(update={"agent_id": row.agent_id})
    if draft.space_id is None and row.space_id is not None:
        draft = draft.model_copy(update={"space_id": row.space_id})
    if (
        draft.tenant_id != row.tenant_id
        or draft.created_by != row.owner_user_id
        or draft.draft_id != row.draft_id
        or draft.revision != row.revision
        or draft.spec.name != row.name
        or draft.updated_at != row.updated_at
    ):
        raise ValueError(f"Corrupt Agent Draft persistence envelope: {row.draft_id}")
    return draft


class PostgresAgentDraftRepository:
    """Durable Draft storage with owner isolation and atomic revision CAS."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def add(self, draft: AgentDraft) -> None:
        async with self._sessions() as session:
            session.add(
                AgentDraftRow(
                    tenant_id=draft.tenant_id,
                    owner_user_id=draft.created_by,
                    draft_id=draft.draft_id,
                    name=draft.spec.name,
                    revision=draft.revision,
                    schema_version=AGENT_DRAFT_SCHEMA_VERSION,
                    updated_at=draft.updated_at,
                    payload=_draft_payload(draft),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ConflictError(f"Agent draft already exists: {draft.draft_id}") from error

    async def get(self, tenant_id: str, owner_user_id: str, draft_id: str) -> AgentDraft:
        async with self._sessions() as session:
            row = await session.get(AgentDraftRow, (tenant_id, owner_user_id, draft_id))
            if row is None:
                raise NotFoundError(f"Agent draft not found: {draft_id}")
            return _load_draft(row)

    async def list_for_user(self, tenant_id: str, owner_user_id: str) -> list[AgentDraft]:
        statement = (
            select(AgentDraftRow)
            .where(
                AgentDraftRow.tenant_id == tenant_id,
                AgentDraftRow.owner_user_id == owner_user_id,
            )
            .order_by(AgentDraftRow.updated_at.desc(), AgentDraftRow.draft_id.desc())
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
            return [_load_draft(row) for row in rows]

    async def list_summaries(
        self, tenant_id: str, owner_user_id: str
    ) -> list[AgentDraftSummary]:
        statement = (
            select(
                AgentDraftRow.draft_id,
                AgentDraftRow.name,
                AgentDraftRow.payload["spec"]["displayName"].as_string(),
                AgentDraftRow.payload["spec"]["domain"].as_string(),
                AgentDraftRow.payload["spec"]["version"].as_string(),
                AgentDraftRow.payload["spec"]["template"].as_string(),
                AgentDraftRow.revision,
                AgentDraftRow.updated_at,
                AgentDraftRow.payload["publishedVersion"].as_string(),
            )
            .where(
                AgentDraftRow.tenant_id == tenant_id,
                AgentDraftRow.owner_user_id == owner_user_id,
            )
            .order_by(AgentDraftRow.updated_at.desc(), AgentDraftRow.draft_id.desc())
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        return [
            AgentDraftSummary(
                draftId=row[0],
                name=row[1],
                displayName=row[2],
                domain=row[3],
                version=row[4],
                template=row[5],
                revision=row[6],
                updatedAt=row[7],
                publishedVersion=row[8],
            )
            for row in rows
        ]

    async def list_all_for_tenant(self, tenant_id: str) -> list[AgentDraft]:
        statement = (
            select(AgentDraftRow)
            .where(AgentDraftRow.tenant_id == tenant_id)
            .order_by(AgentDraftRow.updated_at.desc(), AgentDraftRow.draft_id.desc())
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
            return [_load_draft(row) for row in rows]

    async def replace(self, expected_revision: int, draft: AgentDraft) -> None:
        if draft.revision != expected_revision + 1:
            raise ConflictError("Agent draft replacement must increment revision once")
        statement = (
            update(AgentDraftRow)
            .where(
                AgentDraftRow.tenant_id == draft.tenant_id,
                AgentDraftRow.owner_user_id == draft.created_by,
                AgentDraftRow.draft_id == draft.draft_id,
                AgentDraftRow.revision == expected_revision,
            )
            .values(
                name=draft.spec.name,
                agent_id=draft.agent_id,
                space_id=draft.space_id,
                revision=draft.revision,
                schema_version=AGENT_DRAFT_SCHEMA_VERSION,
                updated_at=draft.updated_at,
                payload=_draft_payload(draft),
            )
        )
        async with self._sessions() as session:
            result = await session.execute(statement)
            if cast(CursorResult[Any], result).rowcount:
                await session.commit()
                return
            actual_revision = await session.scalar(
                select(AgentDraftRow.revision).where(
                    AgentDraftRow.tenant_id == draft.tenant_id,
                    AgentDraftRow.owner_user_id == draft.created_by,
                    AgentDraftRow.draft_id == draft.draft_id,
                )
            )
            await session.rollback()
            if actual_revision is None:
                raise NotFoundError(f"Agent draft not found: {draft.draft_id}")
            raise ConflictError(
                "Agent draft revision changed: "
                f"expected={expected_revision} actual={actual_revision}"
            )


    async def get_by_agent(
        self, tenant_id: str, agent_id: str
    ) -> AgentDraft | None:
        statement = select(AgentDraftRow).where(
            AgentDraftRow.tenant_id == tenant_id,
            AgentDraftRow.agent_id == agent_id,
        )
        async with self._sessions() as session:
            row = (await session.scalars(statement)).first()
            return None if row is None else _load_draft(row)

    async def get_shared(self, tenant_id: str, draft_id: str) -> AgentDraft | None:
        statement = select(AgentDraftRow).where(
            AgentDraftRow.tenant_id == tenant_id,
            AgentDraftRow.draft_id == draft_id,
            AgentDraftRow.space_id.is_not(None),
        )
        async with self._sessions() as session:
            row = (await session.scalars(statement)).first()
            return None if row is None else _load_draft(row)

    async def move_owner(
        self, tenant_id: str, from_user_id: str, to_user_id: str, name: str
    ) -> int:
        if from_user_id == to_user_id:
            return 0
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentDraftRow)
                    .where(
                        AgentDraftRow.tenant_id == tenant_id,
                        AgentDraftRow.owner_user_id == from_user_id,
                        AgentDraftRow.name == name,
                    )
                    .with_for_update()
                )
            ).all()
            for row in rows:
                payload = dict(row.payload)
                payload["createdBy"] = to_user_id
                payload["updatedBy"] = to_user_id
                session.add(
                    AgentDraftRow(
                        tenant_id=tenant_id,
                        owner_user_id=to_user_id,
                        draft_id=row.draft_id,
                        agent_id=row.agent_id,
                        space_id=row.space_id,
                        name=row.name,
                        revision=row.revision,
                        schema_version=row.schema_version,
                        updated_at=row.updated_at,
                        payload=payload,
                    )
                )
                await session.delete(row)
            await session.commit()
            return len(rows)
