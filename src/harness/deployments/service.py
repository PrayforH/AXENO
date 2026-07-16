"""Promotion and rollback use cases over immutable snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from harness.auth.audit import AuditService
from harness.core.errors import ConflictError, NotFoundError
from harness.core.models import AgentVersionStatus
from harness.core.ports import AgentRegistry
from harness.deployments.models import (
    Deployment,
    DeploymentResolution,
    DeploymentSnapshot,
    DeploymentStatus,
    DeploymentView,
    Environment,
    EnvironmentName,
    PromoteRequest,
    RollbackRequest,
)
from harness.deployments.queue import DeploymentTask, DeploymentTaskQueue
from harness.deployments.repositories import DeploymentRepository, EnvironmentRepository
from harness.evals.service import EvalControlPlaneService
from harness.quota.models import QuotaResource, ResourceReservation
from harness.quota.service import QuotaService
from harness.studio.catalog import default_capability_catalog
from harness.studio.models import ExecutionProfileMetadata
from harness.studio.preview_service import PreviewService

QualityGate = Callable[[str, str, str], Awaitable[object]]
ExecutionProfileResolver = Callable[[str, str], Awaitable[ExecutionProfileMetadata]]


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class DeploymentService:
    def __init__(
        self,
        *,
        environments: EnvironmentRepository,
        deployments: DeploymentRepository,
        queue: DeploymentTaskQueue,
        registry: AgentRegistry,
        evals: EvalControlPlaneService,
        previews: PreviewService | None = None,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
        quality_gate: QualityGate | None = None,
        execution_profile_resolver: ExecutionProfileResolver | None = None,
        quotas: QuotaService | None = None,
    ) -> None:
        self._environments = environments
        self._deployments = deployments
        self._queue = queue
        self._registry = registry
        self._evals = evals
        self._previews = previews
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids = id_generator or _id
        self._quality_gate = quality_gate
        self._execution_profile_resolver = execution_profile_resolver
        self._quotas = quotas

    async def _execution_profile(self, tenant_id: str, profile_id: str) -> ExecutionProfileMetadata:
        if self._execution_profile_resolver is not None:
            return await self._execution_profile_resolver(tenant_id, profile_id)
        profile = next(
            (
                item
                for item in default_capability_catalog().execution_profiles
                if item.profile_id == profile_id
            ),
            None,
        )
        if profile is None or not profile.enabled:
            raise ConflictError(f"Execution Profile is unavailable: {profile_id}")
        return profile

    async def environment(
        self, tenant_id: str, agent_name: str, name: EnvironmentName
    ) -> Environment:
        try:
            return await self._environments.get(tenant_id, agent_name, name)
        except NotFoundError:
            value = Environment(
                tenantId=tenant_id,
                agentName=agent_name,
                name=name,
                revision=0,
                updatedAt=self._clock(),
            )
            try:
                await self._environments.add(value)
            except ConflictError:
                return await self._environments.get(tenant_id, agent_name, name)
            return value

    async def list_environments(self, tenant_id: str, agent_name: str) -> list[Environment]:
        existing = {
            item.name: item
            for item in await self._environments.list_for_agent(tenant_id, agent_name)
        }
        return [
            existing.get(name) or await self.environment(tenant_id, agent_name, name)
            for name in EnvironmentName
        ]

    async def promote(
        self, *, tenant_id: str, user_id: str, request: PromoteRequest
    ) -> DeploymentView:
        existing = await self._deployments.find_by_idempotency(tenant_id, request.idempotency_key)
        if existing is not None:
            return await self._same_promote(existing, request)
        environment = await self.environment(tenant_id, request.agent_name, request.environment)
        if environment.revision != request.expected_environment_revision:
            raise ConflictError("Environment revision changed before promotion")
        version = await self._registry.get(tenant_id, request.agent_name, request.agent_version)
        if version.status is not AgentVersionStatus.PUBLISHED or not version.package_hash:
            raise ConflictError("Promotion requires an immutable published Agent package")
        gate = await self._evals.require_promotion_allowed(
            tenant_id, request.agent_name, request.agent_version
        )
        if self._quality_gate is not None:
            await self._quality_gate(tenant_id, request.agent_name, request.agent_version)
        if request.preview_id:
            if self._previews is None:
                raise ConflictError("Preview verification is unavailable")
            preview = await self._previews.get(tenant_id, request.preview_id)
            if (
                preview.stale
                or preview.status.value != "ready"
                or preview.package_hash != version.package_hash
            ):
                raise ConflictError("Promotion Preview does not prove this Agent package")
        profile = await self._execution_profile(tenant_id, request.execution_profile)
        if not profile.enabled:
            raise ConflictError("Execution Profile is disabled")
        if request.environment is EnvironmentName.PRODUCTION and (
            profile.sandbox_provider == "local" or not profile.production_allowed
        ):
            raise ConflictError("Local or unsafe Execution Profile cannot target production")
        profile_payload = profile.model_dump(mode="json", by_alias=True)
        profile_hash = hashlib.sha256(
            json.dumps(
                profile_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        snapshot = DeploymentSnapshot(
            tenantId=tenant_id,
            snapshotId=self._ids("deployment_snapshot"),
            agentName=request.agent_name,
            agentVersion=request.agent_version,
            environment=request.environment,
            manifestHash=version.manifest_hash,
            packageHash=version.package_hash,
            imageDigest=request.image_digest,
            executionProfile=request.execution_profile,
            executionProfileVersion=profile.version,
            executionProfileHash=profile_hash,
            config=request.config,
            evalGatePassed=gate.passed,
            evalRequiredDatasets=gate.required_datasets,
            previewId=request.preview_id,
            createdBy=user_id,
            createdAt=self._clock(),
        )
        reservation: ResourceReservation | None = None
        if self._quotas is not None:
            reservation = await self._quotas.reserve(
                tenant_id=tenant_id,
                resource=QuotaResource.DEPLOYMENT_PROMOTIONS,
                amount=1,
                subject_id=f"deployment:{request.idempotency_key}",
                idempotency_key=f"deployment:{request.idempotency_key}:promotion",
                agent_name=request.agent_name,
                environment=request.environment.value,
            )
        try:
            await self._deployments.add_snapshot(snapshot)
        except Exception:
            if reservation is not None and self._quotas is not None:
                await self._quotas.release(reservation)
            raise
        deployment = Deployment(
            tenantId=tenant_id,
            deploymentId=self._ids("deployment"),
            agentName=request.agent_name,
            environment=request.environment,
            action="promote",
            targetSnapshotId=snapshot.snapshot_id,
            previousSnapshotId=environment.healthy_snapshot_id,
            canaryPercent=request.canary_percent,
            expectedEnvironmentRevision=environment.revision,
            idempotencyKey=request.idempotency_key,
            requestedBy=user_id,
            status=DeploymentStatus.QUEUED,
            createdAt=self._clock(),
            updatedAt=self._clock(),
        )
        try:
            await self._deployments.add(deployment)
        except ConflictError:
            concurrent = await self._deployments.find_by_idempotency(
                tenant_id, request.idempotency_key
            )
            if concurrent is None:
                if reservation is not None and self._quotas is not None:
                    await self._quotas.release(reservation)
                raise
            if reservation is not None and self._quotas is not None:
                await self._quotas.commit(reservation)
            return await self._same_promote(concurrent, request)
        except Exception:
            if reservation is not None and self._quotas is not None:
                await self._quotas.release(reservation)
            raise
        await self._queue.enqueue(
            DeploymentTask(tenant_id=tenant_id, deployment_id=deployment.deployment_id)
        )
        await self._record(deployment, user_id, "studio.deployment.promote")
        if reservation is not None and self._quotas is not None:
            await self._quotas.commit(reservation)
        return DeploymentView(deployment=deployment, target=snapshot, environment=environment)

    async def rollback(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_name: str,
        environment_name: EnvironmentName,
        request: RollbackRequest,
    ) -> DeploymentView:
        existing = await self._deployments.find_by_idempotency(tenant_id, request.idempotency_key)
        if existing is not None:
            target = await self._deployments.get_snapshot(tenant_id, existing.target_snapshot_id)
            if (
                existing.action != "rollback"
                or existing.agent_name != agent_name
                or existing.environment is not environment_name
                or target.snapshot_id != request.snapshot_id
            ):
                raise ConflictError("Deployment idempotency key was reused for another rollback")
            return await self.view(tenant_id, existing.deployment_id)
        environment = await self.environment(tenant_id, agent_name, environment_name)
        if environment.revision != request.expected_environment_revision:
            raise ConflictError("Environment revision changed before rollback")
        snapshot = await self._deployments.get_snapshot(tenant_id, request.snapshot_id)
        if (
            snapshot.agent_name != agent_name
            or snapshot.environment is not environment_name
            or not snapshot.eval_gate_passed
        ):
            raise ConflictError(
                "Rollback requires a historical verified Snapshot from this environment"
            )
        deployment = Deployment(
            tenantId=tenant_id,
            deploymentId=self._ids("deployment"),
            agentName=agent_name,
            environment=environment_name,
            action="rollback",
            targetSnapshotId=snapshot.snapshot_id,
            previousSnapshotId=environment.healthy_snapshot_id,
            canaryPercent=100,
            expectedEnvironmentRevision=environment.revision,
            idempotencyKey=request.idempotency_key,
            requestedBy=user_id,
            status=DeploymentStatus.QUEUED,
            createdAt=self._clock(),
            updatedAt=self._clock(),
        )
        await self._deployments.add(deployment)
        await self._queue.enqueue(
            DeploymentTask(tenant_id=tenant_id, deployment_id=deployment.deployment_id)
        )
        await self._record(deployment, user_id, "studio.deployment.rollback")
        return DeploymentView(deployment=deployment, target=snapshot, environment=environment)

    async def view(self, tenant_id: str, deployment_id: str) -> DeploymentView:
        deployment = await self._deployments.get(tenant_id, deployment_id)
        return DeploymentView(
            deployment=deployment,
            target=await self._deployments.get_snapshot(tenant_id, deployment.target_snapshot_id),
            environment=await self.environment(
                tenant_id, deployment.agent_name, deployment.environment
            ),
        )

    async def list(self, tenant_id: str, agent_name: str) -> list[DeploymentView]:
        return [
            await self.view(tenant_id, item.deployment_id)
            for item in await self._deployments.list_for_agent(tenant_id, agent_name)
        ]

    async def snapshots(self, tenant_id: str, agent_name: str) -> list[DeploymentSnapshot]:
        return await self._deployments.list_snapshots(tenant_id, agent_name)

    async def resolve(
        self, tenant_id: str, agent_name: str, environment_name: EnvironmentName, routing_key: str
    ) -> DeploymentResolution:
        environment = await self._environments.get(tenant_id, agent_name, environment_name)
        if not environment.routes:
            raise ConflictError(
                f"Environment has no active deployment: {agent_name}/{environment_name}"
            )
        bucket = int(hashlib.sha256(routing_key.encode()).hexdigest()[:8], 16) % 100
        cumulative = 0
        selected = environment.routes[-1]
        for route in environment.routes:
            cumulative += route.weight
            if bucket < cumulative:
                selected = route
                break
        snapshot = await self._deployments.get_snapshot(tenant_id, selected.snapshot_id)
        return DeploymentResolution(
            agentName=agent_name,
            agentVersion=snapshot.agent_version,
            environment=environment_name,
            snapshotId=snapshot.snapshot_id,
        )

    async def _same_promote(self, existing: Deployment, request: PromoteRequest) -> DeploymentView:
        target = await self._deployments.get_snapshot(
            existing.tenant_id, existing.target_snapshot_id
        )
        if (
            existing.action != "promote"
            or target.agent_version != request.agent_version
            or existing.environment is not request.environment
            or existing.canary_percent != request.canary_percent
        ):
            raise ConflictError("Deployment idempotency key was reused for another promotion")
        return await self.view(existing.tenant_id, existing.deployment_id)

    async def _record(self, deployment: Deployment, user_id: str, action: str) -> None:
        if self._audit:
            await self._audit.record(
                tenant_id=deployment.tenant_id,
                user_id=user_id,
                action=action,
                resource_type="deployment",
                resource_id=deployment.deployment_id,
                outcome="success",
                details={
                    "agent_name": deployment.agent_name,
                    "environment": deployment.environment.value,
                    "target_snapshot_id": deployment.target_snapshot_id,
                    "expected_revision": deployment.expected_environment_revision,
                },
            )
