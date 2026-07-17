import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from daytona import DaytonaNotFoundError

from harness.core.models import Run, RunStatus
from harness.sandbox import daytona as daytona_module
from harness.sandbox.base import SandboxHandle, SandboxIsolation
from harness.sandbox.daytona import (
    DaytonaRemoteSandbox,
    DaytonaSandboxProvider,
    SdkDaytonaRemoteSession,
)


def test_configure_default_ca_bundle_falls_back_to_certifi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(
        daytona_module.ssl,
        "get_default_verify_paths",
        lambda: SimpleNamespace(cafile=None),
    )
    monkeypatch.setattr(daytona_module.certifi, "where", lambda: "/trusted/cacert.pem")

    daytona_module.configure_default_ca_bundle()

    assert daytona_module.os.environ["SSL_CERT_FILE"] == "/trusted/cacert.pem"


def test_configure_default_ca_bundle_replaces_missing_default_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(
        daytona_module.ssl,
        "get_default_verify_paths",
        lambda: SimpleNamespace(cafile="/missing/system-ca.pem"),
    )
    monkeypatch.setattr(daytona_module.certifi, "where", lambda: "/trusted/cacert.pem")

    daytona_module.configure_default_ca_bundle()

    assert daytona_module.os.environ["SSL_CERT_FILE"] == "/trusted/cacert.pem"


@pytest.mark.asyncio
async def test_remote_session_end_input_uses_a_framed_stdin_close_marker() -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.inputs: list[str] = []
            self.commands: list[str] = []
            self.suppress_input_echo: bool | None = None

        async def create_session(self, _session_id: str) -> None:
            return None

        async def execute_session_command(
            self, _session_id: str, request: object
        ) -> SimpleNamespace:
            self.commands.append(str(cast(Any, request).command))
            self.suppress_input_echo = cast(Any, request).suppress_input_echo
            return SimpleNamespace(cmd_id="command-a")

        async def get_session_command_logs_async(
            self,
            _session_id: str,
            _command_id: str,
            _stdout: object,
            _stderr: object,
        ) -> None:
            return None

        async def send_session_command_input(
            self, _session_id: str, _command_id: str, data: str
        ) -> None:
            self.inputs.append(data)

    process = FakeProcess()
    session = SdkDaytonaRemoteSession(
        SimpleNamespace(process=process)  # type: ignore[arg-type]
    )
    await session.start(
        ["claude", "--system-prompt", "proprietary agent instructions"],
        "/home/daytona",
        {"ANTHROPIC_AUTH_TOKEN": "private-token"},
    )

    await session.end_input()

    assert len(process.inputs) == 2
    assert "private-token" not in process.commands[0]
    assert "private-token" not in process.inputs[0]
    assert "proprietary agent instructions" not in process.commands[0]
    assert "proprietary agent instructions" not in process.inputs[0]
    assert process.suppress_input_echo is True
    assert process.inputs[1].startswith("__HARNESS_END_INPUT_")
    assert process.inputs[1].endswith("__\n")
    assert "\x04" not in process.inputs[1]
    assert "while IFS= read -r line" in process.commands[0]
    assert "while IFS= read -r encoded" in process.commands[0]
    assert process.inputs[1].strip() in process.commands[0]


@pytest.mark.asyncio
async def test_remote_session_rejects_invalid_environment_before_starting() -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.started = False

        async def create_session(self, _session_id: str) -> None:
            self.started = True

    process = FakeProcess()
    session = SdkDaytonaRemoteSession(
        SimpleNamespace(process=process)  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="invalid remote environment"):
        await session.start(["claude"], "/home/daytona", {"BAD-NAME": "value"})

    assert process.started is False


@pytest.mark.asyncio
async def test_remote_session_stdin_frames_reconstruct_environment_and_argv(
    tmp_path: Path,
) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.command = ""
            self.inputs: list[str] = []

        async def create_session(self, _session_id: str) -> None:
            return None

        async def execute_session_command(
            self, _session_id: str, request: object
        ) -> SimpleNamespace:
            self.command = str(cast(Any, request).command)
            return SimpleNamespace(cmd_id="command-a")

        async def get_session_command_logs_async(
            self,
            _session_id: str,
            _command_id: str,
            _stdout: object,
            _stderr: object,
        ) -> None:
            return None

        async def send_session_command_input(
            self, _session_id: str, _command_id: str, data: str
        ) -> None:
            self.inputs.append(data)

    process = FakeProcess()
    session = SdkDaytonaRemoteSession(
        SimpleNamespace(process=process)  # type: ignore[arg-type]
    )
    await session.start(
        [
            "sh",
            "-c",
            'printf "%s|%s" "$PRIVATE_VALUE" "$1"',
            "harness-test",
            "argument with spaces",
        ],
        str(tmp_path),
        {"PRIVATE_VALUE": "secret value"},
    )
    await session.end_input()

    completed = subprocess.run(
        process.command,
        shell=True,
        check=True,
        capture_output=True,
        text=True,
        input="".join(process.inputs),
    )

    assert completed.stdout == "secret value|argument with spaces"
    assert "secret value" not in process.command
    assert "argument with spaces" not in process.command


class FakeRemoteCommandSession:
    def __init__(self) -> None:
        self.started: tuple[list[str], str, dict[str, str]] | None = None
        self.stdout = [b"remote-ready", None]
        self.stderr = [None]
        self.ended = False
        self.terminated = False

    async def start(self, argv: list[str], cwd: str, env: dict[str, str]) -> None:
        self.started = (argv, cwd, env)

    async def write(self, data: str) -> None:
        del data

    async def end_input(self) -> None:
        self.ended = True

    async def read_stdout(self) -> bytes | None:
        return self.stdout.pop(0)

    async def read_stderr(self) -> bytes | None:
        return self.stderr.pop(0)

    async def wait(self) -> int:
        return 0

    async def terminate(self) -> None:
        self.terminated = True


class FakeSandbox:
    def __init__(self, sandbox_id: str) -> None:
        self.id = sandbox_id
        self.uploads: dict[str, bytes] = {}
        self.remote_files: dict[str, bytes] = {}
        self.ensured_cli: tuple[str, str] | None = None
        self.ensure_cli_calls = 0
        self.command_session = FakeRemoteCommandSession()

    async def healthcheck(self) -> bool:
        return True

    async def ensure_claude_cli(self, *, version: str, path: str) -> None:
        self.ensure_cli_calls += 1
        self.ensured_cli = (version, path)

    async def create_folder(self, path: str) -> None:
        del path

    async def remove_tree(self, path: str) -> None:
        del path

    async def upload(self, remote_path: str, content: bytes) -> None:
        self.uploads[remote_path] = content

    async def list_files(
        self, remote_path: str
    ) -> list[tuple[str, bool, int | None]]:
        prefix = remote_path.rstrip("/") + "/"
        return [
            (path, False, len(content))
            for path, content in self.remote_files.items()
            if path.startswith(prefix)
        ]

    async def download(self, remote_path: str) -> bytes:
        return self.remote_files[remote_path]

    def remote_session(self) -> Any:
        return self.command_session


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


def run(
    *,
    existing: str | None = None,
    run_id: str = "run-a",
    session_id: str = "session-a",
) -> Run:
    return Run(
        run_id=run_id,
        session_id=session_id,
        tenant_id="tenant-a",
        status=RunStatus.PROVISIONING,
        idempotency_key="daytona",
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        updated_at=datetime(2026, 7, 13, tzinfo=UTC),
        input={"daytona_sandbox_id": existing} if existing else {},
    )


class WarmFakeSandbox(FakeSandbox):
    def __init__(self, sandbox_id: str, name: str) -> None:
        super().__init__(sandbox_id)
        self.name = name
        self.removed: list[str] = []
        self.healthy = True

    async def healthcheck(self) -> bool:
        return self.healthy

    async def remove_tree(self, path: str) -> None:
        self.removed.append(path)


class WarmFakeClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.by_name: dict[str, WarmFakeSandbox] = {}
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.deleted: list[str] = []

    async def create(self, **parameters: Any) -> WarmFakeSandbox:
        sandbox = WarmFakeSandbox(
            f"daytona-{len(self.created) + 1}",
            str(parameters["name"]),
        )
        self.created.append(parameters)
        self.by_name[sandbox.name] = sandbox
        return sandbox

    async def get(self, sandbox_id: str) -> WarmFakeSandbox:
        sandbox = self.by_name.get(sandbox_id)
        if sandbox is None:
            sandbox = next(
                (
                    item
                    for item in self.by_name.values()
                    if item.id == sandbox_id
                ),
                None,
            )
        if sandbox is None:
            raise DaytonaNotFoundError("missing", status_code=404)
        return sandbox

    async def start(self, sandbox: DaytonaRemoteSandbox) -> None:
        self.started.append(sandbox.id)

    async def stop(self, sandbox: DaytonaRemoteSandbox) -> None:
        self.stopped.append(sandbox.id)

    async def delete(self, sandbox: DaytonaRemoteSandbox) -> None:
        self.deleted.append(sandbox.id)
        for name, item in tuple(self.by_name.items()):
            if item.id == sandbox.id:
                del self.by_name[name]


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
        cli_path="/home/daytona/.local/bin/claude",
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
    assert client.sandbox.ensured_cli == (
        "2.1.206",
        "/home/daytona/.local/bin/claude",
    )
    assert client.created["snapshot"] == "claude-harness-v1"
    assert client.created["auto_stop_interval"] == 15
    assert client.created["auto_delete_interval"] == 60
    assert client.created["labels"] == {
        "harness.tenant": "tenant-a",
        "harness.session": "session-a",
        "harness.run": "run-a",
    }
    assert handle.runtime_transport_factory is not None
    transport_options = ClaudeAgentOptions()
    handle.runtime_transport_factory(transport_options)
    assert transport_options.env["CLAUDE_CONFIG_DIR"].startswith(
        "/workspace/harness/.claude-config/"
    )
    assert client.sandbox.uploads[
        "/workspace/harness/run-a/inputs/facts.txt"
    ] == b"facts"
    assert generated == b"generated"
    assert client.stopped == ["daytona-new"]
    assert client.deleted == ["daytona-new"]


@pytest.mark.asyncio
async def test_provider_reuses_and_starts_named_sandbox(tmp_path: Path) -> None:
    client = FakeClient()
    provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        delete_on_destroy=True,
    )

    handle = await provider.provision(run(existing="daytona-existing"))
    await provider.destroy(handle)

    assert handle.sandbox_id == "daytona-existing"
    assert handle.remote_workspace == "/home/daytona/harness/run-a"
    assert client.created is None
    assert client.started == ["daytona-existing"]
    assert client.stopped == ["daytona-existing"]
    assert client.deleted == []


@pytest.mark.asyncio
async def test_provider_reuses_warm_sandbox_for_same_session(tmp_path: Path) -> None:
    client = WarmFakeClient()
    now = [100.0]
    provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        delete_on_destroy=True,
        session_reuse_enabled=True,
        session_idle_timeout_seconds=600,
        monotonic=lambda: now[0],
    )

    first = await provider.provision(run(run_id="run-a"))
    await provider.prepare(first)
    await provider.destroy(first)
    second = await provider.provision(run(run_id="run-b"))
    await provider.prepare(second)
    await provider.destroy(second)

    assert first.sandbox_id == second.sandbox_id
    assert len(client.created) == 1
    assert client.started == []
    assert client.stopped == []
    assert client.deleted == []
    sandbox = next(iter(client.by_name.values()))
    assert sandbox.removed == [
        "/home/daytona/harness/run-a",
        "/home/daytona/harness/run-b",
    ]
    assert sandbox.ensure_cli_calls == 1


@pytest.mark.asyncio
async def test_provider_serializes_concurrent_runs_in_same_session(
    tmp_path: Path,
) -> None:
    client = WarmFakeClient()
    provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        session_reuse_enabled=True,
    )

    first = await provider.provision(run(run_id="run-a"))
    blocked = asyncio.create_task(provider.provision(run(run_id="run-b")))
    await asyncio.sleep(0)

    assert not blocked.done()

    await provider.destroy(first)
    second = await asyncio.wait_for(blocked, timeout=1)
    await provider.destroy(second)

    assert first.sandbox_id == second.sandbox_id
    assert len(client.created) == 1


@pytest.mark.asyncio
async def test_provider_recovers_session_sandbox_after_provider_restart(
    tmp_path: Path,
) -> None:
    client = WarmFakeClient()
    first_provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        session_reuse_enabled=True,
    )
    first = await first_provider.provision(run(run_id="run-a"))
    await first_provider.destroy(first)

    restarted_provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        session_reuse_enabled=True,
    )
    second = await restarted_provider.provision(run(run_id="run-b"))
    await restarted_provider.destroy(second)

    assert first.sandbox_id == second.sandbox_id
    assert len(client.created) == 1
    assert client.started == [first.sandbox_id]


@pytest.mark.asyncio
async def test_provider_rebuilds_unhealthy_warm_session_sandbox(
    tmp_path: Path,
) -> None:
    client = WarmFakeClient()
    provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        delete_on_destroy=True,
        session_reuse_enabled=True,
    )
    first = await provider.provision(run(run_id="run-a"))
    await provider.destroy(first)
    client.by_name[next(iter(client.by_name))].healthy = False

    second = await provider.provision(run(run_id="run-b"))
    await provider.destroy(second)

    assert first.sandbox_id != second.sandbox_id
    assert len(client.created) == 2
    assert first.sandbox_id in client.stopped
    assert first.sandbox_id in client.deleted


@pytest.mark.asyncio
async def test_provider_reaps_expired_warm_session_sandbox(tmp_path: Path) -> None:
    client = WarmFakeClient()
    now = [100.0]
    provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        delete_on_destroy=True,
        session_reuse_enabled=True,
        session_idle_timeout_seconds=60,
        monotonic=lambda: now[0],
    )
    handle = await provider.provision(run())
    await provider.destroy(handle)

    now[0] = 161.0
    reaped = await provider.reap_expired()

    assert reaped == 1
    assert client.stopped == [handle.sandbox_id]
    assert client.deleted == [handle.sandbox_id]


@pytest.mark.asyncio
async def test_provider_evicts_oldest_warm_session_above_capacity(
    tmp_path: Path,
) -> None:
    client = WarmFakeClient()
    now = [100.0]
    provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        delete_on_destroy=True,
        session_reuse_enabled=True,
        warm_pool_max_sessions=2,
        monotonic=lambda: now[0],
    )

    handles: list[SandboxHandle] = []
    for index, session_id in enumerate(("session-a", "session-b", "session-c")):
        handle = await provider.provision(
            run(run_id=f"run-{index}", session_id=session_id)
        )
        handles.append(handle)
        await provider.destroy(handle)
        now[0] += 1

    assert len(client.created) == 3
    assert client.stopped == [handles[0].sandbox_id]
    assert client.deleted == [handles[0].sandbox_id]
    assert sorted(sandbox.id for sandbox in client.by_name.values()) == sorted(
        [handles[1].sandbox_id, handles[2].sandbox_id]
    )


@pytest.mark.asyncio
async def test_provider_executes_remote_argv_without_returning_environment(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    provider = DaytonaSandboxProvider(client=client, local_root=tmp_path)
    handle = await provider.provision(run())

    result = await provider.execute(
        handle,
        ("bash", "-lc", "printf ready"),
        environment={"PRIVATE_VALUE": "secret"},
    )

    assert result.exit_code == 0
    assert result.stdout == "remote-ready"
    assert client.sandbox.command_session.started == (
        ["bash", "-lc", "printf ready"],
        "/home/daytona/harness/run-a",
        {"PRIVATE_VALUE": "secret"},
    )
    assert client.sandbox.command_session.ended
    assert client.sandbox.command_session.terminated
    assert "secret" not in result.model_dump_json()
    await provider.destroy(handle)


@pytest.mark.asyncio
async def test_provider_rejects_remote_workspace_over_collection_limit(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    provider = DaytonaSandboxProvider(
        client=client,
        local_root=tmp_path,
        max_collect_bytes=4,
    )
    handle = await provider.provision(run())
    client.sandbox.remote_files[
        "/home/daytona/harness/run-a/oversized.bin"
    ] = b"12345"

    with pytest.raises(ValueError, match="collection size limit"):
        await provider.collect(handle)

    await provider.destroy(handle)
