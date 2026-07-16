from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from harness.deployments.models import (
    Deployment,
    DeploymentRoute,
    DeploymentSnapshot,
    DeploymentStatus,
    Environment,
    EnvironmentName,
)
from harness.storage.database import SessionFactory
from harness.storage.deployment_repository import (
    PostgresDeploymentRepository,
    PostgresEnvironmentRepository,
)

DatabaseFixture = tuple[AsyncEngine, SessionFactory]


@pytest.mark.asyncio
async def test_postgres_deployment_state_is_durable_and_fenced(
    database: DatabaseFixture,
) -> None:
    _engine, sessions = database
    environments = PostgresEnvironmentRepository(sessions)
    deployments = PostgresDeploymentRepository(sessions)
    now = datetime.now(UTC)
    environment = Environment(
        tenantId="tenant-a",
        agentName="durable-agent",
        name=EnvironmentName.PRODUCTION,
        revision=0,
        updatedAt=now,
    )
    snapshot = DeploymentSnapshot(
        tenantId="tenant-a",
        snapshotId="snapshot-a",
        agentName="durable-agent",
        agentVersion="1.0.0",
        environment=EnvironmentName.PRODUCTION,
        manifestHash="a" * 64,
        packageHash="b" * 64,
        imageDigest="sha256:" + "c" * 64,
        executionProfile="isolated-default",
        config={"LOG_LEVEL": "info"},
        evalGatePassed=True,
        evalRequiredDatasets=1,
        createdBy="release-manager",
        createdAt=now,
    )
    deployment = Deployment(
        tenantId="tenant-a",
        deploymentId="deployment-a",
        agentName="durable-agent",
        environment=EnvironmentName.PRODUCTION,
        action="promote",
        targetSnapshotId=snapshot.snapshot_id,
        canaryPercent=100,
        expectedEnvironmentRevision=0,
        idempotencyKey="release-a",
        requestedBy="release-manager",
        status=DeploymentStatus.QUEUED,
        createdAt=now,
        updatedAt=now,
    )
    await environments.add(environment)
    await deployments.add_snapshot(snapshot)
    await deployments.add(deployment)

    reconciling = deployment.model_copy(
        update={"status": DeploymentStatus.RECONCILING, "fencing_token": 1}
    )
    assert await deployments.compare_and_set(DeploymentStatus.QUEUED, reconciling)
    assert not await deployments.compare_and_set(DeploymentStatus.QUEUED, reconciling)
    active = environment.model_copy(
        update={
            "revision": 1,
            "routes": (DeploymentRoute(snapshotId=snapshot.snapshot_id, weight=100),),
            "healthy_snapshot_id": snapshot.snapshot_id,
        }
    )
    assert await environments.compare_and_set(0, active)
    assert not await environments.compare_and_set(0, active)

    restarted_environments = PostgresEnvironmentRepository(sessions)
    restarted_deployments = PostgresDeploymentRepository(sessions)
    assert (
        await restarted_environments.get(
            "tenant-a", "durable-agent", EnvironmentName.PRODUCTION
        )
        == active
    )
    assert await restarted_deployments.get_snapshot("tenant-a", "snapshot-a") == snapshot
    assert await restarted_deployments.get("tenant-a", "deployment-a") == reconciling
    assert (
        await restarted_deployments.find_by_idempotency("tenant-a", "release-a")
        == reconciling
    )
