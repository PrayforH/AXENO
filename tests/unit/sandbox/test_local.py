from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.core.models import Run, RunStatus
from harness.sandbox.base import SandboxIsolation
from harness.sandbox.local import LocalSandboxProvider


@pytest.mark.asyncio
async def test_local_provider_marks_workspace_as_non_isolated(tmp_path: Path) -> None:
    provider = LocalSandboxProvider(root=tmp_path)
    run = Run(
        run_id="run-local",
        session_id="session-local",
        tenant_id="tenant-a",
        status=RunStatus.PROVISIONING,
        idempotency_key="local",
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        updated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    handle = await provider.provision(run)

    assert handle.provider == "local"
    assert handle.isolation_level is SandboxIsolation.WORKSPACE

