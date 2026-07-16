"""PostgreSQL adapters for durable evaluation control-plane facts."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.exc import IntegrityError

from harness.core.errors import ConflictError, NotFoundError
from harness.evals.models import (
    EvalCaseResult,
    EvalDatasetVersion,
    EvalRun,
    EvalRunStatus,
)
from harness.storage.database import SessionFactory
from harness.storage.models import EvalCaseResultRow, EvalDatasetVersionRow, EvalRunRow


def _payload(value: EvalDatasetVersion | EvalRun | EvalCaseResult) -> dict[str, Any]:
    return value.model_dump(mode="json", by_alias=True)


def _load_dataset(row: EvalDatasetVersionRow) -> EvalDatasetVersion:
    value = EvalDatasetVersion.model_validate(row.payload)
    if (
        value.tenant_id != row.tenant_id
        or value.dataset_id != row.dataset_id
        or value.version != row.version
        or value.agent_name != row.agent_name
        or value.required != row.required
        or value.created_at != row.created_at
    ):
        raise ValueError(f"Corrupt Eval Dataset envelope: {row.dataset_id}@{row.version}")
    return value


def _load_run(row: EvalRunRow) -> EvalRun:
    value = EvalRun.model_validate(row.payload)
    if (
        value.tenant_id != row.tenant_id
        or value.eval_run_id != row.eval_run_id
        or value.dataset_id != row.dataset_id
        or value.dataset_version != row.dataset_version
        or value.agent_name != row.agent_name
        or value.agent_version != row.agent_version
        or value.idempotency_key != row.idempotency_key
        or value.status.value != row.status
        or value.fencing_token != row.fencing_token
        or value.created_at != row.created_at
    ):
        raise ValueError(f"Corrupt Eval Run envelope: {row.eval_run_id}")
    return value


def _load_result(row: EvalCaseResultRow) -> EvalCaseResult:
    value = EvalCaseResult.model_validate(row.payload)
    if (
        value.tenant_id != row.tenant_id
        or value.eval_run_id != row.eval_run_id
        or value.case_id != row.case_id
        or value.status.value != row.status
        or value.passed != row.passed
        or value.completed_at != row.completed_at
    ):
        raise ValueError(
            f"Corrupt Eval Case Result envelope: {row.eval_run_id}/{row.case_id}"
        )
    return value


class PostgresEvalDatasetRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def add(self, dataset: EvalDatasetVersion) -> None:
        async with self._sessions() as session:
            session.add(
                EvalDatasetVersionRow(
                    tenant_id=dataset.tenant_id,
                    dataset_id=dataset.dataset_id,
                    version=dataset.version,
                    agent_name=dataset.agent_name,
                    required=dataset.required,
                    created_at=dataset.created_at,
                    payload=_payload(dataset),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ConflictError("Eval Dataset Version already exists") from error

    async def get(
        self, tenant_id: str, dataset_id: str, version: int
    ) -> EvalDatasetVersion:
        async with self._sessions() as session:
            row = await session.get(
                EvalDatasetVersionRow, (tenant_id, dataset_id, version)
            )
            if row is None:
                raise NotFoundError(
                    f"Eval Dataset Version not found: {dataset_id}@{version}"
                )
            return _load_dataset(row)

    async def list_for_tenant(self, tenant_id: str) -> list[EvalDatasetVersion]:
        statement = (
            select(EvalDatasetVersionRow)
            .where(EvalDatasetVersionRow.tenant_id == tenant_id)
            .order_by(
                EvalDatasetVersionRow.created_at.desc(),
                EvalDatasetVersionRow.dataset_id.desc(),
                EvalDatasetVersionRow.version.desc(),
            )
        )
        async with self._sessions() as session:
            return [_load_dataset(row) for row in (await session.scalars(statement)).all()]

    async def next_version(self, tenant_id: str, dataset_id: str) -> int:
        statement = select(func.max(EvalDatasetVersionRow.version)).where(
            EvalDatasetVersionRow.tenant_id == tenant_id,
            EvalDatasetVersionRow.dataset_id == dataset_id,
        )
        async with self._sessions() as session:
            current = await session.scalar(statement)
            return int(current or 0) + 1


class PostgresEvalRunRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def add(self, run: EvalRun) -> None:
        async with self._sessions() as session:
            session.add(
                EvalRunRow(
                    tenant_id=run.tenant_id,
                    eval_run_id=run.eval_run_id,
                    dataset_id=run.dataset_id,
                    dataset_version=run.dataset_version,
                    agent_name=run.agent_name,
                    agent_version=run.agent_version,
                    idempotency_key=run.idempotency_key,
                    status=run.status.value,
                    fencing_token=run.fencing_token,
                    created_at=run.created_at,
                    payload=_payload(run),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ConflictError("Eval Run already exists") from error

    async def get(self, tenant_id: str, eval_run_id: str) -> EvalRun:
        async with self._sessions() as session:
            row = await session.get(EvalRunRow, (tenant_id, eval_run_id))
            if row is None:
                raise NotFoundError(f"Eval Run not found: {eval_run_id}")
            return _load_run(row)

    async def find_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> EvalRun | None:
        statement = select(EvalRunRow).where(
            EvalRunRow.tenant_id == tenant_id,
            EvalRunRow.idempotency_key == idempotency_key,
        )
        async with self._sessions() as session:
            row = await session.scalar(statement)
            return None if row is None else _load_run(row)

    async def list_for_tenant(self, tenant_id: str) -> list[EvalRun]:
        statement = (
            select(EvalRunRow)
            .where(EvalRunRow.tenant_id == tenant_id)
            .order_by(EvalRunRow.created_at.desc(), EvalRunRow.eval_run_id.desc())
        )
        async with self._sessions() as session:
            return [_load_run(row) for row in (await session.scalars(statement)).all()]

    async def compare_and_set(
        self, expected_status: EvalRunStatus, updated: EvalRun
    ) -> bool:
        statement = (
            update(EvalRunRow)
            .where(
                EvalRunRow.tenant_id == updated.tenant_id,
                EvalRunRow.eval_run_id == updated.eval_run_id,
                EvalRunRow.status == expected_status.value,
                EvalRunRow.fencing_token == updated.fencing_token - 1,
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
            if changed:
                await session.commit()
            else:
                await session.rollback()
            return changed

    async def add_case_result(self, result: EvalCaseResult) -> None:
        async with self._sessions() as session:
            session.add(
                EvalCaseResultRow(
                    tenant_id=result.tenant_id,
                    eval_run_id=result.eval_run_id,
                    case_id=result.case_id,
                    status=result.status.value,
                    passed=result.passed,
                    completed_at=result.completed_at,
                    payload=_payload(result),
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                existing = await self._get_case_result(
                    result.tenant_id, result.eval_run_id, result.case_id
                )
                if existing != result:
                    raise ConflictError("Eval Case Result already exists") from error

    async def _get_case_result(
        self, tenant_id: str, eval_run_id: str, case_id: str
    ) -> EvalCaseResult:
        async with self._sessions() as session:
            row = await session.get(
                EvalCaseResultRow, (tenant_id, eval_run_id, case_id)
            )
            if row is None:
                raise NotFoundError(f"Eval Case Result not found: {case_id}")
            return _load_result(row)

    async def list_case_results(
        self, tenant_id: str, eval_run_id: str
    ) -> list[EvalCaseResult]:
        statement = (
            select(EvalCaseResultRow)
            .where(
                EvalCaseResultRow.tenant_id == tenant_id,
                EvalCaseResultRow.eval_run_id == eval_run_id,
            )
            .order_by(EvalCaseResultRow.completed_at, EvalCaseResultRow.case_id)
        )
        async with self._sessions() as session:
            return [_load_result(row) for row in (await session.scalars(statement)).all()]
