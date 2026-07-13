from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from harness.core.models import Run, RunStatus
from harness.sandbox.base import SandboxIsolation
from harness.sandbox.daytona import (
    DaytonaRemoteSandbox,
    DaytonaSandboxProvider,
)


class FakeSandbox:
    def __init__(self, sandbox_id: str) -> None:
        self.id = sandbox_id
        self.uploads: dict[str, bytes] = {}
        self.remote_files: dict[str, bytes] = {}

    async def create_folder(self, path: str) -> None:
        del path

    async def upload(self, remote_path: str, content: bytes) -> None:
        self.uploads[remote_path] = content

    async def list_files(self, remote_path: str) -> list[tuple[str, bool]]:
        prefix = remote_path.rstrip("/") + "/"
        return [
            (path, False) for path in self.remote_files if path.startswith(prefix)
        ]

    async def download(self, remote_path: str) -> bytes:
        return self.remote_files[remote_path]

    def remote_session(self) -> Any:
        return object()


class FakeClient:
    def __init__(self) -> None:
        self.sandbox = FakeSandbox("daytona-new")
        self.created: dict[str, Any] | None = None
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.deleted: list[str] = []

    async def create(self, **parameters: Any) -> FakeSandbox:
        self.created = parameters
        return self.sandbox

    async def get(self, sandbox_id: str) -> FakeSandbox:
        self.sandbox.id = sandbox_id
        return self.sandbox

    async def start(self, sandbox: DaytonaRemoteSandbox) -> None:
        self.started.append(sandbox.id)

    async def stop(self, sandbox: DaytonaRemoteSandbox) -> None:
        self.stopped.append(sandbox.id)

    async def delete(self, sandbox: DaytonaRemoteSandbox) -> None:
        self.deleted.append(sandbox.id)


def run(*, existing: str | None = None) -> Run:
    return Run(
        run_id="run-a",
        session_id="session-a",
        tenant_id="tenant-a",
        status=RunStatus.PROVISIONING,
        idempotency_key="daytona",
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        updated_at=datetime(2026, 7, 13, tzinfo=UTC),
        input={"daytona_sandbox_id": existing} if existing else {},
    )


@pytest.mark.asyncio
async def test_provider_creates_identity_labeled_sandbox_and_syncs_workspace(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        snapshot="claude-harness-v1",
        remote_workspace_root="/workspace/harness",
        cli_version="2.1.206",
        delete_on_destroy=True,
    )
    handle = await provider.provision(run())
    (handle.path / "inputs").mkdir()
    (handle.path / "inputs" / "facts.txt").write_text("facts")

    await provider.prepare(handle)
    client.sandbox.remote_files[
        "/workspace/harness/run-a/generated.txt"
    ] = b"generated"
    await provider.collect(handle)
    generated = (handle.path / "generated.txt").read_bytes()
    await provider.destroy(handle)

    assert client.created is not None
    assert handle.provider == "daytona"
    assert handle.isolation_level is SandboxIsolation.CONTAINER
    assert client.created["snapshot"] == "claude-harness-v1"
    assert client.created["labels"] == {
        "harness.tenant": "tenant-a",
        "harness.session": "session-a",
        "harness.run": "run-a",
    }
    assert client.sandbox.uploads[
        "/workspace/harness/run-a/inputs/facts.txt"
    ] == b"facts"
    assert generated == b"generated"
    assert client.stopped == ["daytona-new"]
    assert client.deleted == ["daytona-new"]


@pytest.mark.asyncio
async def test_provider_reuses_and_starts_named_sandbox(tmp_path: Path) -> None:
    client = FakeClient()
    provider = DaytonaSandboxProvider(client=client, local_root=tmp_path)

    handle = await provider.provision(run(existing="daytona-existing"))

    assert handle.sandbox_id == "daytona-existing"
    assert client.created is None
    assert client.started == ["daytona-existing"]
