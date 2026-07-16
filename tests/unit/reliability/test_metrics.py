from datetime import UTC, datetime, timedelta

import pytest

from harness.adapters.memory import InMemoryEventRepository
from harness.core.events import RunEvent
from harness.reliability.adapters import ObservedEventRepository
from harness.reliability.metrics import ReliabilityMetrics

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def test_prometheus_registry_exports_bounded_summaries_and_counters() -> None:
    metrics = ReliabilityMetrics()
    metrics.observe(
        "harness_api_request_duration_seconds",
        0.25,
        labels={"operation": "run.create", "tenant_id": "must-not-export"},
    )
    metrics.increment(
        "harness_artifact_download_total", labels={"outcome": "success"}
    )
    metrics.observe(
        "harness_api_request_duration_seconds",
        0.5,
        labels={"operation": "/v1/tenant-a/private-path"},
    )

    rendered = metrics.render_prometheus()

    assert "# TYPE harness_api_request_duration_seconds summary" in rendered
    assert (
        'harness_api_request_duration_seconds{operation="run.create",quantile="0.95"} 0.25'
        in rendered
    )
    assert 'harness_artifact_download_total{outcome="success"} 1' in rendered
    assert 'operation="unknown"' in rendered
    assert "/v1/tenant-a/private-path" not in rendered
    assert "tenant_id" not in rendered
    assert rendered.endswith("\n")


@pytest.mark.asyncio
async def test_event_visibility_observer_records_each_event_only_once() -> None:
    raw = InMemoryEventRepository()
    metrics = ReliabilityMetrics()
    observed = ObservedEventRepository(raw, metrics, clock=lambda: NOW)
    await raw.append(
        RunEvent(
            event_id="event-0",
            tenant_id="tenant-a",
            run_id="run-1",
            session_id="session-1",
            sequence=1,
            type="run.queued",
            timestamp=NOW - timedelta(minutes=5),
            payload={},
        )
    )
    await raw.append(
        RunEvent(
            event_id="event-1",
            tenant_id="tenant-a",
            run_id="run-1",
            session_id="session-1",
            sequence=2,
            type="run.queued",
            timestamp=NOW - timedelta(seconds=2),
            payload={},
        )
    )

    await observed.list_after("tenant-a", "run-1", 1)
    await observed.list_after("tenant-a", "run-1", 1)

    value, count = metrics.quantile(
        "harness_event_visibility_delay_seconds", 0.95
    )
    assert value == 2
    assert count == 1
