import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from harness.core.models import Run, RunStatus
from harness.sandbox import daytona as daytona_module
from harness.sandbox.base import SandboxIsolation
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
        self.command_session = FakeRemoteCommandSession()

    async def ensure_claude_cli(self, *, version: str, path: str) -> None:
        self.ensured_cli = (version, path)

    async def create_folder(self, path: str) -> None:
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
