from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from harness.core.errors import ConflictError, NotFoundError
from harness.lifecycle.models import (
    DataLifecycleJob,
    LegalHold,
    LifecycleJobStatus,
    RetentionPolicy,
)
from harness.storage.database import SessionFactory
from harness.storage.models import (
    DataLifecycleJobRow,
    LegalHoldRow,
    RetentionPolicyRow,
)


class PostgresDataLifecycleRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def list_policy_tenants(self) -> Sequence[str]:
        async with self._sessions() as session:
            values = await session.scalars(select(RetentionPolicyRow.tenant_id).distinct())
            return tuple(values.all())

    async def get_policy(self, tenant_id: str) -> RetentionPolicy | None:
        async with self._sessions() as session:
            row = await session.get(RetentionPolicyRow, (tenant_id, "tenant-default"))
            return RetentionPolicy.model_validate(row.payload) if row else None

    async def replace_policy(
        self, policy: RetentionPolicy, *, expected_revision: int
    ) -> RetentionPolicy:
        async with self._sessions() as session:
            row = await session.scalar(
                select(RetentionPolicyRow)
                .where(
                    RetentionPolicyRow.tenant_id == policy.tenant_id,
                    RetentionPolicyRow.policy_id == policy.policy_id,
                )
                .with_for_update()
            )
            actual = row.revision if row else 0
            if actual != expected_revision:
                raise ConflictError(
                    "retention policy revision changed: "
                    f"expected={expected_revision} actual={actual}"
                )
            if row is None:
                session.add(
                    RetentionPolicyRow(
                        tenant_id=policy.tenant_id,
                        policy_id=policy.policy_id,
                        revision=policy.revision,
                        payload=policy.model_dump(mode="json", by_alias=True),
                    )
                )
            else:
                row.revision = policy.revision
                row.payload = policy.model_dump(mode="json", by_alias=True)
            await session.commit()
            return policy

    async def add_hold(self, hold: LegalHold) -> None:
        async with self._sessions() as session:
            session.add(
                LegalHoldRow(
                    tenant_id=hold.tenant_id,
                    hold_id=hold.hold_id,
                    active=hold.active,
                    scope_kind=hold.scope.kind.value,
                    subject_id=hold.scope.subject_id,
                    payload=hold.model_dump(mode="json", by_alias=True),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ConflictError(f"legal hold already exists: {hold.hold_id}") from error

    async def get_hold(self, tenant_id: str, hold_id: str) -> LegalHold:
        async with self._sessions() as session:
            row = await session.get(LegalHoldRow, (tenant_id, hold_id))
            if row is None:
                raise NotFoundError(f"legal hold not found: {hold_id}")
            return LegalHold.model_validate(row.payload)

    async def update_hold(self, hold: LegalHold) -> LegalHold:
        async with self._sessions() as session:
            row = await session.get(LegalHoldRow, (hold.tenant_id, hold.hold_id))
            if row is None:
                raise NotFoundError(f"legal hold not found: {hold.hold_id}")
            row.active = hold.active
            row.payload = hold.model_dump(mode="json", by_alias=True)
            await session.commit()
            return hold

    async def list_holds(self, tenant_id: str) -> Sequence[LegalHold]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(LegalHoldRow).where(LegalHoldRow.tenant_id == tenant_id)
                )
            ).all()
            return tuple(LegalHold.model_validate(row.payload) for row in rows)

    async def add_job(self, job: DataLifecycleJob) -> DataLifecycleJob:
        async with self._sessions() as session:
            session.add(self._job_row(job))
            try:
                await session.commit()
                return job
            except IntegrityError:
                await session.rollback()
        existing = await self.find_job_by_idempotency(job.tenant_id, job.idempotency_key)
        if existing is None:
            raise ConflictError("data lifecycle job idempotency conflict")
        if existing.kind is not job.kind or existing.scope != job.scope:
            raise ConflictError("data lifecycle idempotency key was reused")
        return existing

    async def find_job_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> DataLifecycleJob | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(DataLifecycleJobRow).where(
                    DataLifecycleJobRow.tenant_id == tenant_id,
                    DataLifecycleJobRow.idempotency_key == idempotency_key,
                )
            )
            return self._job(row) if row else None

    async def get_job(self, tenant_id: str, job_id: str) -> DataLifecycleJob:
        async with self._sessions() as session:
            row = await session.get(DataLifecycleJobRow, (tenant_id, job_id))
            if row is None:
                raise NotFoundError(f"data lifecycle job not found: {job_id}")
            return self._job(row)

    async def list_jobs(self, tenant_id: str, *, limit: int) -> Sequence[DataLifecycleJob]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(DataLifecycleJobRow)
                    .where(DataLifecycleJobRow.tenant_id == tenant_id)
                    .order_by(DataLifecycleJobRow.created_at.desc())
                    .limit(limit)
                )
            ).all()
            return tuple(self._job(row) for row in rows)

    async def list_runnable(self, *, limit: int) -> Sequence[DataLifecycleJob]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(DataLifecycleJobRow)
                    .where(DataLifecycleJobRow.status == LifecycleJobStatus.QUEUED.value)
                    .order_by(DataLifecycleJobRow.created_at)
                    .limit(limit)
                )
            ).all()
            return tuple(self._job(row) for row in rows)

    async def compare_and_set(
        self, expected_status: LifecycleJobStatus, job: DataLifecycleJob
    ) -> bool:
        async with self._sessions() as session:
            row = await session.scalar(
                select(DataLifecycleJobRow)
                .where(
                    DataLifecycleJobRow.tenant_id == job.tenant_id,
                    DataLifecycleJobRow.job_id == job.job_id,
                )
                .with_for_update()
            )
            if (
                row is None
                or row.status != expected_status.value
                or row.fencing_token + 1 != job.fencing_token
            ):
                return False
            row.status = job.status.value
            row.fencing_token = job.fencing_token
            row.updated_at = job.updated_at
            row.payload = job.model_dump(mode="json", by_alias=True)
            await session.commit()
            return True

    @staticmethod
    def _job(row: DataLifecycleJobRow) -> DataLifecycleJob:
        return DataLifecycleJob.model_validate(row.payload)

    @staticmethod
    def _job_row(job: DataLifecycleJob) -> DataLifecycleJobRow:
        return DataLifecycleJobRow(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            idempotency_key=job.idempotency_key,
            status=job.status.value,
            fencing_token=job.fencing_token,
            created_at=job.created_at,
            updated_at=job.updated_at,
            payload=job.model_dump(mode="json", by_alias=True),
        )
