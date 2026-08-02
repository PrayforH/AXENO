"""PostgreSQL Preview Deployment repository with status CAS."""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError

from harness.core.errors import ConflictError, NotFoundError
from harness.storage.database import SessionFactory
from harness.storage.models import PreviewDeploymentRow
from harness.studio.preview_models import PreviewDeployment, PreviewStatus


def _payload(preview: PreviewDeployment) -> dict[str, Any]:
    return preview.model_dump(mode="json", by_alias=True)


def _load(row: PreviewDeploymentRow) -> PreviewDeployment:
    preview = PreviewDeployment.model_validate(row.payload)
    if (
        preview.tenant_id != row.tenant_id
        or preview.preview_id != row.preview_id
        or preview.requested_by != row.requested_by
        or preview.draft_id != row.draft_id
        or preview.idempotency_key != row.idempotency_key
        or preview.status.value != row.status
        or preview.fencing_token != row.fencing_token
        or preview.created_at != row.created_at
        or preview.expires_at != row.expires_at
    ):
        raise ValueError(f"Corrupt Preview persistence envelope: {row.preview_id}")
    return preview


class PostgresPreviewRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def add(self, preview: PreviewDeployment) -> None:
        async with self._sessions() as session:
            session.add(
                PreviewDeploymentRow(
                    tenant_id=preview.tenant_id,
                    preview_id=preview.preview_id,
                    requested_by=preview.requested_by,
                    draft_id=preview.draft_id,
                    idempotency_key=preview.idempotency_key,
                    status=preview.status.value,
                    fencing_token=preview.fencing_token,
                    created_at=preview.created_at,
                    expires_at=preview.expires_at,
                    payload=_payload(preview),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ConflictError("Preview Deployment already exists") from error

    async def get(self, tenant_id: str, preview_id: str) -> PreviewDeployment:
        async with self._sessions() as session:
            row = await session.get(PreviewDeploymentRow, (tenant_id, preview_id))
            if row is None:
                raise NotFoundError(f"Preview Deployment not found: {preview_id}")
            return _load(row)

    async def get_for_user(
        self, tenant_id: str, owner_user_id: str, preview_id: str
    ) -> PreviewDeployment:
        async with self._sessions() as session:
            row = await session.get(PreviewDeploymentRow, (tenant_id, preview_id))
            if row is None or row.requested_by != owner_user_id:
                raise NotFoundError(f"Preview Deployment not found: {preview_id}")
            return _load(row)

    async def find_by_idempotency(
        self, tenant_id: str, owner_user_id: str, idempotency_key: str
    ) -> PreviewDeployment | None:
        statement = select(PreviewDeploymentRow).where(
            PreviewDeploymentRow.tenant_id == tenant_id,
            PreviewDeploymentRow.requested_by == owner_user_id,
            PreviewDeploymentRow.idempotency_key == idempotency_key,
        )
        async with self._sessions() as session:
            row = await session.scalar(statement)
            return None if row is None else _load(row)

    async def list_for_user(self, tenant_id: str, owner_user_id: str) -> list[PreviewDeployment]:
        statement = (
            select(PreviewDeploymentRow)
            .where(
                PreviewDeploymentRow.tenant_id == tenant_id,
                PreviewDeploymentRow.requested_by == owner_user_id,
            )
            .order_by(
                PreviewDeploymentRow.created_at.desc(),
                PreviewDeploymentRow.preview_id.desc(),
            )
        )
        async with self._sessions() as session:
            return [_load(row) for row in (await session.scalars(statement)).all()]

    async def list_for_tenant(self, tenant_id: str) -> list[PreviewDeployment]:
        statement = (
            select(PreviewDeploymentRow)
            .where(PreviewDeploymentRow.tenant_id == tenant_id)
            .order_by(
                PreviewDeploymentRow.created_at.desc(),
                PreviewDeploymentRow.preview_id.desc(),
            )
        )
        async with self._sessions() as session:
            return [_load(row) for row in (await session.scalars(statement)).all()]

    async def compare_and_set(
        self, expected_status: PreviewStatus, updated: PreviewDeployment
    ) -> bool:
        statement = (
            update(PreviewDeploymentRow)
            .where(
                PreviewDeploymentRow.tenant_id == updated.tenant_id,
                PreviewDeploymentRow.preview_id == updated.preview_id,
                PreviewDeploymentRow.status == expected_status.value,
                PreviewDeploymentRow.fencing_token == updated.fencing_token - 1,
            )
            .values(
                status=updated.status.value,
                fencing_token=updated.fencing_token,
                expires_at=updated.expires_at,
                payload=_payload(updated),
            )
        )
        async with self._sessions() as session:
            result = await session.execute(statement)
            changed = bool(cast(CursorResult[Any], result).rowcount)
            if changed:
                await session.commit()
            else:
                await session.rollback()
            return changed

    async def list_expired_active(
        self, expires_at_or_before: datetime, *, limit: int
    ) -> list[PreviewDeployment]:
        if limit < 1:
            raise ValueError("Preview reaper limit must be positive")
        terminal = tuple(status.value for status in PreviewStatus if status.is_terminal)
        statement = (
            select(PreviewDeploymentRow)
            .where(
                PreviewDeploymentRow.expires_at <= expires_at_or_before,
                PreviewDeploymentRow.status.not_in(terminal),
            )
            .order_by(
                PreviewDeploymentRow.expires_at,
                PreviewDeploymentRow.preview_id,
            )
            .limit(limit)
        )
        async with self._sessions() as session:
            return [_load(row) for row in (await session.scalars(statement)).all()]
