from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.lifecycle.models import (
    DataLifecycleJob,
    LegalHold,
    LifecycleJobStatus,
    RetentionPolicy,
)


class DataLifecycleRepository(Protocol):
    async def list_policy_tenants(self) -> Sequence[str]: ...

    async def get_policy(self, tenant_id: str) -> RetentionPolicy | None: ...

    async def replace_policy(
        self, policy: RetentionPolicy, *, expected_revision: int
    ) -> RetentionPolicy: ...

    async def add_hold(self, hold: LegalHold) -> None: ...

    async def get_hold(self, tenant_id: str, hold_id: str) -> LegalHold: ...

    async def update_hold(self, hold: LegalHold) -> LegalHold: ...

    async def list_holds(self, tenant_id: str) -> Sequence[LegalHold]: ...

    async def add_job(self, job: DataLifecycleJob) -> DataLifecycleJob: ...

    async def find_job_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> DataLifecycleJob | None: ...

    async def get_job(self, tenant_id: str, job_id: str) -> DataLifecycleJob: ...

    async def list_jobs(self, tenant_id: str, *, limit: int) -> Sequence[DataLifecycleJob]: ...

    async def list_runnable(self, *, limit: int) -> Sequence[DataLifecycleJob]: ...

    async def compare_and_set(
        self, expected_status: LifecycleJobStatus, job: DataLifecycleJob
    ) -> bool: ...


class InMemoryDataLifecycleRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._policies: dict[tuple[str, str], RetentionPolicy] = {}
        self._holds: dict[tuple[str, str], LegalHold] = {}
        self._jobs: dict[tuple[str, str], DataLifecycleJob] = {}
        self._idempotency: dict[tuple[str, str], str] = {}

    async def list_policy_tenants(self) -> Sequence[str]:
        return tuple(sorted({tenant_id for tenant_id, _ in self._policies}))

    async def get_policy(self, tenant_id: str) -> RetentionPolicy | None:
        return self._policies.get((tenant_id, "tenant-default"))

    async def replace_policy(
        self, policy: RetentionPolicy, *, expected_revision: int
    ) -> RetentionPolicy:
        async with self._lock:
            key = (policy.tenant_id, policy.policy_id)
            current = self._policies.get(key)
            actual = current.revision if current is not None else 0
            if actual != expected_revision:
                raise ConflictError(
                    "retention policy revision changed: "
                    f"expected={expected_revision} actual={actual}"
                )
            self._policies[key] = policy
            return policy

    async def add_hold(self, hold: LegalHold) -> None:
        async with self._lock:
            key = (hold.tenant_id, hold.hold_id)
            if key in self._holds:
                raise ConflictError(f"legal hold already exists: {hold.hold_id}")
            self._holds[key] = hold

    async def get_hold(self, tenant_id: str, hold_id: str) -> LegalHold:
        try:
            return self._holds[(tenant_id, hold_id)]
        except KeyError as error:
            raise NotFoundError(f"legal hold not found: {hold_id}") from error

    async def update_hold(self, hold: LegalHold) -> LegalHold:
        async with self._lock:
            key = (hold.tenant_id, hold.hold_id)
            if key not in self._holds:
                raise NotFoundError(f"legal hold not found: {hold.hold_id}")
            self._holds[key] = hold
            return hold

    async def list_holds(self, tenant_id: str) -> Sequence[LegalHold]:
        return tuple(
            hold for (stored_tenant, _), hold in self._holds.items() if stored_tenant == tenant_id
        )

    async def add_job(self, job: DataLifecycleJob) -> DataLifecycleJob:
        async with self._lock:
            idempotency = (job.tenant_id, job.idempotency_key)
            existing_id = self._idempotency.get(idempotency)
            if existing_id is not None:
                return self._jobs[(job.tenant_id, existing_id)]
            self._jobs[(job.tenant_id, job.job_id)] = job
            self._idempotency[idempotency] = job.job_id
            return job

    async def find_job_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> DataLifecycleJob | None:
        job_id = self._idempotency.get((tenant_id, idempotency_key))
        return self._jobs.get((tenant_id, job_id)) if job_id else None

    async def get_job(self, tenant_id: str, job_id: str) -> DataLifecycleJob:
        try:
            return self._jobs[(tenant_id, job_id)]
        except KeyError as error:
            raise NotFoundError(f"data lifecycle job not found: {job_id}") from error

    async def list_jobs(self, tenant_id: str, *, limit: int) -> Sequence[DataLifecycleJob]:
        jobs = [job for (stored_tenant, _), job in self._jobs.items() if stored_tenant == tenant_id]
        return tuple(sorted(jobs, key=lambda item: item.created_at, reverse=True)[:limit])

    async def list_runnable(self, *, limit: int) -> Sequence[DataLifecycleJob]:
        jobs = [job for job in self._jobs.values() if job.status is LifecycleJobStatus.QUEUED]
        return tuple(sorted(jobs, key=lambda item: item.created_at)[:limit])

    async def compare_and_set(
        self, expected_status: LifecycleJobStatus, job: DataLifecycleJob
    ) -> bool:
        async with self._lock:
            key = (job.tenant_id, job.job_id)
            current = self._jobs.get(key)
            if (
                current is None
                or current.status is not expected_status
                or current.fencing_token + 1 != job.fencing_token
            ):
                return False
            self._jobs[key] = job
            return True
