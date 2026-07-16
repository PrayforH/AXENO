import asyncio
from datetime import UTC, datetime

import pytest

from harness.quota.models import QuotaResource, ReplaceQuotaPolicyRequest
from harness.quota.repositories import QuotaExceededError
from harness.quota.service import QuotaService
from harness.storage.quota_repository import PostgresQuotaRepository
from tests.integration.storage.conftest import DatabaseFixture


@pytest.mark.asyncio
async def test_postgres_quota_reservation_is_atomic_and_durable(
    database: DatabaseFixture,
) -> None:
    _engine, sessions = database
    sequence = 0

    def ids(prefix: str) -> str:
        nonlocal sequence
        sequence += 1
        return f"{prefix}-{sequence}"

    quotas = QuotaService(
        PostgresQuotaRepository(sessions),
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
        id_generator=ids,
    )
    await quotas.replace_policy(
        tenant_id="tenant-a",
        user_id="owner",
        policy_id="tenant-default",
        request=ReplaceQuotaPolicyRequest(
            expectedRevision=0,
            limits={QuotaResource.CONCURRENT_RUNS: 2},
        ),
    )

    results = await asyncio.gather(
        *(
            quotas.reserve(
                tenant_id="tenant-a",
                resource=QuotaResource.CONCURRENT_RUNS,
                amount=1,
                subject_id=f"run-{index}",
                idempotency_key=f"run-{index}",
            )
            for index in range(8)
        ),
        return_exceptions=True,
    )

    assert len([item for item in results if not isinstance(item, Exception)]) == 2
    assert len([item for item in results if isinstance(item, QuotaExceededError)]) == 6
    restarted = QuotaService(PostgresQuotaRepository(sessions))
    view = await restarted.usage("tenant-a")
    assert len(view.active_reservations) == 2
    assert view.counters[0].reserved == 2
