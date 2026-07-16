"""PostgreSQL deployment lifecycle repositories."""

from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError

from harness.core.errors import ConflictError, NotFoundError
from harness.deployments.models import (
    Deployment,
    DeploymentSnapshot,
    DeploymentStatus,
    Environment,
    EnvironmentName,
)
from harness.storage.database import SessionFactory
from harness.storage.models import DeploymentRow, DeploymentSnapshotRow, EnvironmentRow


def _payload(value: Environment | DeploymentSnapshot | Deployment) -> dict[str, Any]:
    return value.model_dump(mode="json", by_alias=True)


def _environment(row: EnvironmentRow) -> Environment:
    value = Environment.model_validate(row.payload)
    if (value.tenant_id, value.agent_name, value.name.value, value.revision, value.updated_at) != (
        row.tenant_id,
        row.agent_name,
        row.name,
        row.revision,
        row.updated_at,
    ):
        raise ValueError("Corrupt Environment persistence envelope")
    return value


def _snapshot(row: DeploymentSnapshotRow) -> DeploymentSnapshot:
    value = DeploymentSnapshot.model_validate(row.payload)
    if (
        value.tenant_id,
        value.snapshot_id,
        value.agent_name,
        value.agent_version,
        value.environment.value,
        value.created_at,
    ) != (
        row.tenant_id,
        row.snapshot_id,
        row.agent_name,
        row.agent_version,
        row.environment,
        row.created_at,
    ):
        raise ValueError("Corrupt Deployment Snapshot persistence envelope")
    return value


def _deployment(row: DeploymentRow) -> Deployment:
    value = Deployment.model_validate(row.payload)
    if (
        value.tenant_id,
        value.deployment_id,
        value.agent_name,
        value.environment.value,
        value.idempotency_key,
        value.status.value,
        value.fencing_token,
        value.created_at,
    ) != (
        row.tenant_id,
        row.deployment_id,
        row.agent_name,
        row.environment,
        row.idempotency_key,
        row.status,
        row.fencing_token,
        row.created_at,
    ):
        raise ValueError("Corrupt Deployment persistence envelope")
    return value


class PostgresEnvironmentRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def add(self, environment: Environment) -> None:
        async with self._sessions() as session:
            session.add(
                EnvironmentRow(
                    tenant_id=environment.tenant_id,
                    agent_name=environment.agent_name,
                    name=environment.name.value,
                    revision=environment.revision,
                    updated_at=environment.updated_at,
                    payload=_payload(environment),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ConflictError("Environment already exists") from error

    async def get(self, tenant_id: str, agent_name: str, name: EnvironmentName) -> Environment:
        async with self._sessions() as session:
            row = await session.get(EnvironmentRow, (tenant_id, agent_name, name.value))
            if row is None:
                raise NotFoundError(f"Environment not found: {agent_name}/{name}")
            return _environment(row)

    async def list_for_agent(self, tenant_id: str, agent_name: str) -> list[Environment]:
        statement = (
            select(EnvironmentRow)
            .where(EnvironmentRow.tenant_id == tenant_id, EnvironmentRow.agent_name == agent_name)
            .order_by(EnvironmentRow.name)
        )
        async with self._sessions() as session:
            return [_environment(row) for row in (await session.scalars(statement)).all()]

    async def compare_and_set(self, expected_revision: int, updated: Environment) -> bool:
        statement = (
            update(EnvironmentRow)
            .where(
                EnvironmentRow.tenant_id == updated.tenant_id,
                EnvironmentRow.agent_name == updated.agent_name,
                EnvironmentRow.name == updated.name.value,
                EnvironmentRow.revision == expected_revision,
            )
            .values(
                revision=updated.revision, updated_at=updated.updated_at, payload=_payload(updated)
            )
        )
        async with self._sessions() as session:
            result = await session.execute(statement)
            changed = bool(cast(CursorResult[Any], result).rowcount)
            await (session.commit() if changed else session.rollback())
            return changed


class PostgresDeploymentRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def add_snapshot(self, snapshot: DeploymentSnapshot) -> None:
        async with self._sessions() as session:
            session.add(
                DeploymentSnapshotRow(
                    tenant_id=snapshot.tenant_id,
                    snapshot_id=snapshot.snapshot_id,
                    agent_name=snapshot.agent_name,
                    agent_version=snapshot.agent_version,
                    environment=snapshot.environment.value,
                    created_at=snapshot.created_at,
                    payload=_payload(snapshot),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                existing = await self.get_snapshot(snapshot.tenant_id, snapshot.snapshot_id)
                if existing != snapshot:
                    raise ConflictError("Deployment Snapshot already exists") from error

    async def get_snapshot(self, tenant_id: str, snapshot_id: str) -> DeploymentSnapshot:
        async with self._sessions() as session:
            row = await session.get(DeploymentSnapshotRow, (tenant_id, snapshot_id))
            if row is None:
                raise NotFoundError(f"Deployment Snapshot not found: {snapshot_id}")
            return _snapshot(row)

    async def list_snapshots(self, tenant_id: str, agent_name: str) -> list[DeploymentSnapshot]:
        statement = (
            select(DeploymentSnapshotRow)
            .where(
                DeploymentSnapshotRow.tenant_id == tenant_id,
                DeploymentSnapshotRow.agent_name == agent_name,
            )
            .order_by(
                DeploymentSnapshotRow.created_at.desc(), DeploymentSnapshotRow.snapshot_id.desc()
            )
        )
        async with self._sessions() as session:
            return [_snapshot(row) for row in (await session.scalars(statement)).all()]

    async def add(self, deployment: Deployment) -> None:
        async with self._sessions() as session:
            session.add(
                DeploymentRow(
                    tenant_id=deployment.tenant_id,
                    deployment_id=deployment.deployment_id,
                    agent_name=deployment.agent_name,
                    environment=deployment.environment.value,
                    idempotency_key=deployment.idempotency_key,
                    status=deployment.status.value,
                    fencing_token=deployment.fencing_token,
                    created_at=deployment.created_at,
                    payload=_payload(deployment),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ConflictError("Deployment already exists") from error

    async def get(self, tenant_id: str, deployment_id: str) -> Deployment:
        async with self._sessions() as session:
            row = await session.get(DeploymentRow, (tenant_id, deployment_id))
            if row is None:
                raise NotFoundError(f"Deployment not found: {deployment_id}")
            return _deployment(row)

    async def find_by_idempotency(self, tenant_id: str, key: str) -> Deployment | None:
        statement = select(DeploymentRow).where(
            DeploymentRow.tenant_id == tenant_id, DeploymentRow.idempotency_key == key
        )
        async with self._sessions() as session:
            row = await session.scalar(statement)
            return None if row is None else _deployment(row)

    async def list_for_agent(self, tenant_id: str, agent_name: str) -> list[Deployment]:
        statement = (
            select(DeploymentRow)
            .where(DeploymentRow.tenant_id == tenant_id, DeploymentRow.agent_name == agent_name)
            .order_by(DeploymentRow.created_at.desc(), DeploymentRow.deployment_id.desc())
        )
        async with self._sessions() as session:
            return [_deployment(row) for row in (await session.scalars(statement)).all()]

    async def compare_and_set(self, expected: DeploymentStatus, updated: Deployment) -> bool:
        statement = (
            update(DeploymentRow)
            .where(
                DeploymentRow.tenant_id == updated.tenant_id,
                DeploymentRow.deployment_id == updated.deployment_id,
                DeploymentRow.status == expected.value,
                DeploymentRow.fencing_token == updated.fencing_token - 1,
            )
            .values(
                status=updated.status.value,
                fencing_token=updated.fencing_token,
                payload=_payload(updated),
            )
        )
        async with self._sessions() as session:
            result = await session.execute(statement)
            changed = bool(cast(CursorResult[Any], result).rowcount)
            await (session.commit() if changed else session.rollback())
            return changed
