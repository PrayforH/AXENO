"""Evaluation persistence ports and deterministic in-memory adapters."""

from __future__ import annotations

import asyncio
from typing import Protocol

from harness.core.errors import ConflictError, NotFoundError
from harness.evals.models import (
    EvalCaseResult,
    EvalDatasetVersion,
    EvalRun,
    EvalRunStatus,
)


class EvalDatasetRepository(Protocol):
    async def add(self, dataset: EvalDatasetVersion) -> None: ...

    async def get(
        self, tenant_id: str, dataset_id: str, version: int
    ) -> EvalDatasetVersion: ...

    async def list_for_tenant(self, tenant_id: str) -> list[EvalDatasetVersion]: ...

    async def next_version(self, tenant_id: str, dataset_id: str) -> int: ...


class EvalRunRepository(Protocol):
    async def add(self, run: EvalRun) -> None: ...

    async def get(self, tenant_id: str, eval_run_id: str) -> EvalRun: ...

    async def find_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> EvalRun | None: ...

    async def list_for_tenant(self, tenant_id: str) -> list[EvalRun]: ...

    async def compare_and_set(
        self, expected_status: EvalRunStatus, updated: EvalRun
    ) -> bool: ...

    async def add_case_result(self, result: EvalCaseResult) -> None: ...

    async def list_case_results(
        self, tenant_id: str, eval_run_id: str
    ) -> list[EvalCaseResult]: ...


class InMemoryEvalDatasetRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, int], EvalDatasetVersion] = {}
        self._lock = asyncio.Lock()

    async def add(self, dataset: EvalDatasetVersion) -> None:
        key = (dataset.tenant_id, dataset.dataset_id, dataset.version)
        async with self._lock:
            if key in self._items:
                raise ConflictError("Eval Dataset Version already exists")
            self._items[key] = dataset

    async def get(
        self, tenant_id: str, dataset_id: str, version: int
    ) -> EvalDatasetVersion:
        try:
            return self._items[(tenant_id, dataset_id, version)]
        except KeyError as error:
            raise NotFoundError(
                f"Eval Dataset Version not found: {dataset_id}@{version}"
            ) from error

    async def list_for_tenant(self, tenant_id: str) -> list[EvalDatasetVersion]:
        return sorted(
            (
                item
                for (stored_tenant, _dataset_id, _version), item in self._items.items()
                if stored_tenant == tenant_id
            ),
            key=lambda item: (item.created_at, item.dataset_id, item.version),
            reverse=True,
        )

    async def next_version(self, tenant_id: str, dataset_id: str) -> int:
        versions = [
            version
            for stored_tenant, stored_id, version in self._items
            if stored_tenant == tenant_id and stored_id == dataset_id
        ]
        return max(versions, default=0) + 1


class InMemoryEvalRunRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], EvalRun] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._results: dict[tuple[str, str, str], EvalCaseResult] = {}
        self._lock = asyncio.Lock()

    async def add(self, run: EvalRun) -> None:
        key = (run.tenant_id, run.eval_run_id)
        idem = (run.tenant_id, run.idempotency_key)
        async with self._lock:
            if key in self._items or idem in self._idempotency:
                raise ConflictError("Eval Run already exists")
            self._items[key] = run
            self._idempotency[idem] = run.eval_run_id

    async def get(self, tenant_id: str, eval_run_id: str) -> EvalRun:
        try:
            return self._items[(tenant_id, eval_run_id)]
        except KeyError as error:
            raise NotFoundError(f"Eval Run not found: {eval_run_id}") from error

    async def find_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> EvalRun | None:
        run_id = self._idempotency.get((tenant_id, idempotency_key))
        return None if run_id is None else self._items[(tenant_id, run_id)]

    async def list_for_tenant(self, tenant_id: str) -> list[EvalRun]:
        return sorted(
            (
                item
                for (stored_tenant, _run_id), item in self._items.items()
                if stored_tenant == tenant_id
            ),
            key=lambda item: (item.created_at, item.eval_run_id),
            reverse=True,
        )

    async def compare_and_set(
        self, expected_status: EvalRunStatus, updated: EvalRun
    ) -> bool:
        key = (updated.tenant_id, updated.eval_run_id)
        async with self._lock:
            current = self._items.get(key)
            if current is None or current.status is not expected_status:
                return False
            if updated.fencing_token != current.fencing_token + 1:
                raise ConflictError("Eval Run fencing token must increment once")
            self._items[key] = updated
            return True

    async def add_case_result(self, result: EvalCaseResult) -> None:
        key = (result.tenant_id, result.eval_run_id, result.case_id)
        async with self._lock:
            existing = self._results.get(key)
            if existing is not None and existing != result:
                raise ConflictError("Eval Case Result already exists")
            self._results[key] = result

    async def list_case_results(
        self, tenant_id: str, eval_run_id: str
    ) -> list[EvalCaseResult]:
        return sorted(
            (
                item
                for (stored_tenant, stored_run, _case_id), item in self._results.items()
                if stored_tenant == tenant_id and stored_run == eval_run_id
            ),
            key=lambda item: item.case_id,
        )
