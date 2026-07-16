from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from harness.auth.audit import AuditService
from harness.core.errors import ConflictError
from harness.core.ports import ArtifactStore
from harness.lifecycle.adapters import LifecycleAdapter
from harness.lifecycle.models import (
    CreateLegalHoldRequest,
    CreateLifecycleJobRequest,
    DataLifecycleJob,
    LegalHold,
    LifecycleAdapterResult,
    LifecycleAdapterStatus,
    LifecycleJobKind,
    LifecycleJobStatus,
    LifecycleOverview,
    LifecycleScope,
    LifecycleScopeKind,
    ReplaceRetentionPolicyRequest,
    RetentionPolicy,
)
from harness.lifecycle.repositories import DataLifecycleRepository


def _ids(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class DataLifecycleService:
    def __init__(
        self,
        repository: DataLifecycleRepository,
        adapters: Sequence[LifecycleAdapter],
        *,
        export_store: ArtifactStore,
        scope_resolver: Callable[
            [str, LifecycleScope], Awaitable[Sequence[LifecycleScope]]
        ]
        | None = None,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
    ) -> None:
        names = [adapter.name for adapter in adapters]
        if len(set(names)) != len(names):
            raise ValueError("lifecycle adapter names must be unique")
        self.repository = repository
        self.adapters = tuple(adapters)
        self._export_store = export_store
        self._scope_resolver = scope_resolver or self._same_scope
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids = id_generator or _ids

    def default_policy(self, tenant_id: str) -> RetentionPolicy:
        return RetentionPolicy(
            tenantId=tenant_id,
            policyId="tenant-default",
            revision=0,
            sessionDays=90,
            artifactDays=90,
            traceDays=30,
            evalDays=365,
            updatedBy="platform-default",
            updatedAt=datetime(1970, 1, 1, tzinfo=UTC),
        )

    async def policy(self, tenant_id: str) -> RetentionPolicy:
        return await self.repository.get_policy(tenant_id) or self.default_policy(tenant_id)

    async def enqueue_due_retention_jobs(self) -> tuple[DataLifecycleJob, ...]:
        """Create at most one scheduled retention job per tenant and UTC day."""

        today = self._clock().date().isoformat()
        created: list[DataLifecycleJob] = []
        for tenant_id in await self.repository.list_policy_tenants():
            try:
                job = await self.create_job(
                    tenant_id=tenant_id,
                    user_id="system:retention",
                    request=CreateLifecycleJobRequest(
                        kind=LifecycleJobKind.RETENTION,
                        scope=LifecycleScope(
                            kind=LifecycleScopeKind.TENANT,
                            subjectId=tenant_id,
                        ),
                        idempotencyKey=f"retention:{today}",
                    ),
                )
            except ConflictError as error:
                if not str(error).startswith("legal_hold_active:"):
                    raise
            else:
                created.append(job)
        return tuple(created)

    async def replace_policy(
        self,
        *,
        tenant_id: str,
        user_id: str,
        request: ReplaceRetentionPolicyRequest,
    ) -> RetentionPolicy:
        policy = RetentionPolicy(
            tenantId=tenant_id,
            policyId="tenant-default",
            revision=request.expected_revision + 1,
            sessionDays=request.session_days,
            artifactDays=request.artifact_days,
            traceDays=request.trace_days,
            evalDays=request.eval_days,
            updatedBy=user_id,
            updatedAt=self._clock(),
        )
        stored = await self.repository.replace_policy(
            policy, expected_revision=request.expected_revision
        )
        await self._record(
            tenant_id,
            user_id,
            "data.retention_policy.replace",
            "retention_policy",
            policy.policy_id,
            "success",
            {"revision": stored.revision},
        )
        return stored

    async def create_hold(
        self,
        *,
        tenant_id: str,
        user_id: str,
        request: CreateLegalHoldRequest,
    ) -> LegalHold:
        self._validate_scope(tenant_id, request.scope)
        hold = LegalHold(
            tenantId=tenant_id,
            holdId=self._ids("hold"),
            scope=request.scope,
            reason=request.reason,
            createdBy=user_id,
            createdAt=self._clock(),
        )
        await self.repository.add_hold(hold)
        await self._record(
            tenant_id,
            user_id,
            "data.legal_hold.create",
            "legal_hold",
            hold.hold_id,
            "success",
            {"scope": hold.scope.model_dump(mode="json", by_alias=True)},
        )
        return hold

    async def release_hold(self, *, tenant_id: str, user_id: str, hold_id: str) -> LegalHold:
        current = await self.repository.get_hold(tenant_id, hold_id)
        if not current.active:
            return current
        released = current.model_copy(
            update={
                "active": False,
                "released_by": user_id,
                "released_at": self._clock(),
            }
        )
        await self.repository.update_hold(released)
        await self._record(
            tenant_id,
            user_id,
            "data.legal_hold.release",
            "legal_hold",
            hold_id,
            "success",
            {},
        )
        return released

    async def create_job(
        self,
        *,
        tenant_id: str,
        user_id: str,
        request: CreateLifecycleJobRequest,
    ) -> DataLifecycleJob:
        self._validate_scope(tenant_id, request.scope)
        existing = await self.repository.find_job_by_idempotency(tenant_id, request.idempotency_key)
        if existing is not None:
            if existing.kind is not request.kind or existing.scope != request.scope:
                raise ConflictError("data lifecycle idempotency key was reused")
            return existing
        if request.kind in {LifecycleJobKind.DELETE, LifecycleJobKind.RETENTION}:
            blocking = await self._blocking_hold(tenant_id, request.scope)
            if blocking is not None:
                await self._record(
                    tenant_id,
                    user_id,
                    "data.lifecycle_job.create",
                    "data_lifecycle_job",
                    None,
                    "denied",
                    {"reason": "legal_hold", "hold_id": blocking.hold_id},
                )
                raise ConflictError(f"legal_hold_active:{blocking.hold_id}")
        now = self._clock()
        retention_cutoffs: dict[str, datetime] = {}
        if request.kind is LifecycleJobKind.RETENTION:
            policy = await self.policy(tenant_id)
            retention_cutoffs = {
                "sessions": now - timedelta(days=policy.session_days),
                "artifacts": now - timedelta(days=policy.artifact_days),
                "traces": now - timedelta(days=policy.trace_days),
                "evals": now - timedelta(days=policy.eval_days),
            }
        job = DataLifecycleJob(
            tenantId=tenant_id,
            jobId=self._ids("lifecycle"),
            kind=request.kind,
            scope=request.scope,
            requestedBy=user_id,
            idempotencyKey=request.idempotency_key,
            status=LifecycleJobStatus.QUEUED,
            adapters=tuple(
                LifecycleAdapterResult(
                    adapter=adapter.name,
                    status=LifecycleAdapterStatus.PENDING,
                    attempts=0,
                    updatedAt=now,
                )
                for adapter in self.adapters
            ),
            retentionCutoffs=retention_cutoffs,
            createdAt=now,
            updatedAt=now,
        )
        stored = await self.repository.add_job(job)
        await self._record(
            tenant_id,
            user_id,
            "data.lifecycle_job.create",
            "data_lifecycle_job",
            stored.job_id,
            "success",
            {
                "kind": stored.kind.value,
                "scope": stored.scope.model_dump(mode="json", by_alias=True),
            },
        )
        return stored

    async def retry_job(self, *, tenant_id: str, user_id: str, job_id: str) -> DataLifecycleJob:
        current = await self.repository.get_job(tenant_id, job_id)
        if current.status not in {
            LifecycleJobStatus.PARTIAL_FAILED,
            LifecycleJobStatus.FAILED,
        }:
            raise ConflictError("only failed data lifecycle jobs can be retried")
        if current.kind in {LifecycleJobKind.DELETE, LifecycleJobKind.RETENTION}:
            blocking = await self._blocking_hold(tenant_id, current.scope)
            if blocking is not None:
                raise ConflictError(f"legal_hold_active:{blocking.hold_id}")
        reset = current.model_copy(
            update={
                "status": LifecycleJobStatus.QUEUED,
                "adapters": tuple(
                    item.model_copy(
                        update={
                            "status": LifecycleAdapterStatus.PENDING,
                            "error_code": None,
                            "error_message": None,
                            "updated_at": self._clock(),
                        }
                    )
                    if (
                        current.kind is LifecycleJobKind.EXPORT
                        or item.status is LifecycleAdapterStatus.FAILED
                    )
                    else item
                    for item in current.adapters
                    if item.adapter != "export-artifact"
                ),
                "updated_at": self._clock(),
                "completed_at": None,
                "fencing_token": current.fencing_token + 1,
            }
        )
        if not await self.repository.compare_and_set(current.status, reset):
            raise ConflictError("data lifecycle job changed before retry")
        await self._record(
            tenant_id,
            user_id,
            "data.lifecycle_job.retry",
            "data_lifecycle_job",
            job_id,
            "success",
            {},
        )
        return reset

    async def overview(self, tenant_id: str) -> LifecycleOverview:
        return LifecycleOverview(
            policy=await self.policy(tenant_id),
            holds=tuple(await self.repository.list_holds(tenant_id)),
            jobs=tuple(await self.repository.list_jobs(tenant_id, limit=100)),
        )

    async def get_job(self, tenant_id: str, job_id: str) -> DataLifecycleJob:
        return await self.repository.get_job(tenant_id, job_id)

    async def list_jobs(self, tenant_id: str, *, limit: int = 100) -> tuple[DataLifecycleJob, ...]:
        return tuple(await self.repository.list_jobs(tenant_id, limit=limit))

    async def download_export(self, tenant_id: str, job_id: str) -> tuple[DataLifecycleJob, bytes]:
        job = await self.repository.get_job(tenant_id, job_id)
        if job.kind is not LifecycleJobKind.EXPORT or not job.export_object_id:
            raise ConflictError("data lifecycle export is not ready")
        return job, await self._export_store.get(tenant_id, job.export_object_id)

    async def _blocking_hold(self, tenant_id: str, scope: LifecycleScope) -> LegalHold | None:
        related_scopes = await self._scope_resolver(tenant_id, scope)
        for hold in await self.repository.list_holds(tenant_id):
            if hold.active and any(
                self._scopes_overlap(hold.scope, related) for related in related_scopes
            ):
                return hold
        return None

    @staticmethod
    async def _same_scope(
        _tenant_id: str, scope: LifecycleScope
    ) -> Sequence[LifecycleScope]:
        return (scope,)

    @staticmethod
    def _scopes_overlap(left: LifecycleScope, right: LifecycleScope) -> bool:
        if left.kind is LifecycleScopeKind.TENANT or right.kind is LifecycleScopeKind.TENANT:
            return True
        return left.kind is right.kind and left.subject_id == right.subject_id

    @staticmethod
    def _validate_scope(tenant_id: str, scope: LifecycleScope) -> None:
        if scope.kind is LifecycleScopeKind.TENANT and scope.subject_id != tenant_id:
            raise ConflictError("tenant lifecycle scope must match authenticated tenant")

    async def _record(
        self,
        tenant_id: str,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
        details: dict[str, object],
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=details,
        )
