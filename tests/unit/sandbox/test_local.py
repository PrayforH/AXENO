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


@pytest.mark.asyncio
async def test_local_provider_executes_argv_with_ephemeral_environment(
    tmp_path: Path,
) -> None:
    provider = LocalSandboxProvider(root=tmp_path)
    run = Run(
        run_id="run-command",
        session_id="session-command",
        tenant_id="tenant-a",
        status=RunStatus.PROVISIONING,
        idempotency_key="command",
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        updated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
    handle = await provider.provision(run)

    result = await provider.execute(
        handle,
        ("bash", "-lc", "printf '%s' \"$PREFLIGHT_VALUE\" > result.txt"),
        environment={"PREFLIGHT_VALUE": "ready"},
    )

    assert result.exit_code == 0
    assert (handle.path / "result.txt").read_text() == "ready"
    await provider.destroy(handle)


@pytest.mark.asyncio
async def test_local_provider_does_not_inherit_worker_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_NEW_API_KEY", "must-not-leak")
    provider = LocalSandboxProvider(root=tmp_path)
    run = Run(
        run_id="run-clean-env",
        session_id="session-clean-env",
        tenant_id="tenant-a",
        status=RunStatus.PROVISIONING,
        idempotency_key="clean-env",
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        updated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
    handle = await provider.provision(run)

    result = await provider.execute(
        handle,
        (
            "python3",
            "-c",
            "import os; print(os.getenv('HARNESS_NEW_API_KEY', 'clean'))",
        ),
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "clean"
    await provider.destroy(handle)
