"""Daytona SandboxProvider plus adapters for the official async SDK."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import shlex
import shutil
import ssl
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast
from uuid import uuid4

import certifi
from claude_agent_sdk import ClaudeAgentOptions
from daytona import (
    AsyncDaytona,
    CreateSandboxFromSnapshotParams,
    DaytonaConfig,
)
from daytona._async.sandbox import AsyncSandbox
from daytona.common.process import SessionExecuteRequest

from harness.core.models import Run
from harness.runtime.daytona_transport import (
    DaytonaClaudeTransport,
    RemoteClaudeSession,
)
from harness.sandbox.base import (
    SandboxCommandResult,
    SandboxHandle,
    SandboxIsolation,
)

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def configure_default_ca_bundle() -> None:
    """Use certifi when this Python installation has no usable default CA file."""
    default_ca_file: object = getattr(ssl.get_default_verify_paths(), "cafile", None)
    default_ca_is_usable = isinstance(default_ca_file, str) and Path(
        default_ca_file
    ).is_file()
    if "SSL_CERT_FILE" not in os.environ and not default_ca_is_usable:
        os.environ["SSL_CERT_FILE"] = certifi.where()


class DaytonaRemoteSandbox(Protocol):
    id: str

    async def ensure_claude_cli(self, *, version: str, path: str) -> None: ...

    async def create_folder(self, path: str) -> None: ...

    async def upload(self, remote_path: str, content: bytes) -> None: ...

    async def list_files(
        self, remote_path: str
    ) -> list[tuple[str, bool, int | None]]: ...

    async def download(self, remote_path: str) -> bytes: ...

    def remote_session(self) -> RemoteClaudeSession: ...


class DaytonaClient(Protocol):
    async def create(self, **parameters: Any) -> DaytonaRemoteSandbox: ...

    async def get(self, sandbox_id: str) -> DaytonaRemoteSandbox: ...

    async def start(self, sandbox: DaytonaRemoteSandbox) -> None: ...

    async def stop(self, sandbox: DaytonaRemoteSandbox) -> None: ...

    async def delete(self, sandbox: DaytonaRemoteSandbox) -> None: ...


class SdkDaytonaRemoteSession:
    def __init__(self, sandbox: AsyncSandbox) -> None:
        self._sandbox = sandbox
        self._session_id = f"harness-{uuid4().hex}"
        self._end_input_marker = f"__HARNESS_END_INPUT_{uuid4().hex}__"
        self._command_id: str | None = None
        self._stdout: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._stderr: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._logs_task: asyncio.Task[None] | None = None

    async def start(self, argv: list[str], cwd: str, env: dict[str, str]) -> None:
        if not argv:
            raise ValueError("remote command argv must not be empty")
        environment_lines: list[str] = []
        for key, value in sorted(env.items()):
            if _ENVIRONMENT_NAME.fullmatch(key) is None:
                raise ValueError(f"invalid remote environment variable name: {key}")
            encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
            environment_lines.append(f"{key}={encoded}")
        argument_lines = [
            base64.b64encode(argument.encode("utf-8")).decode("ascii")
            for argument in argv
        ]
        await self._sandbox.process.create_session(self._session_id)
        environment_marker = f"__HARNESS_END_ENV_{uuid4().hex}__"
        argument_marker = f"__HARNESS_END_ARGV_{uuid4().hex}__"
        stdin_wrapper = (
            'env_marker="$1"; arg_marker="$2"; input_marker="$3"; shift 3; '
            "while IFS= read -r env_line; do "
            '[ "$env_line" = "$env_marker" ] && break; '
            'key="${env_line%%=*}"; encoded="${env_line#*=}"; '
            'value="$(printf "%s" "$encoded" | base64 -d)" || exit 70; '
            'export "$key=$value"; '
            "done; "
            "while IFS= read -r encoded; do "
            '[ "$encoded" = "$arg_marker" ] && break; '
            'value="$(printf "%s" "$encoded" | base64 -d)" || exit 70; '
            'set -- "$@" "$value"; '
            "done; "
            '[ "$#" -gt 0 ] || exit 64; '
            'mcp_config_path=""; '
            'if [ -n "${HARNESS_CLAUDE_MCP_CONFIG:-}" ]; then '
            'mcp_config_path="$(mktemp)"; chmod 600 "$mcp_config_path"; '
            'printf "%s" "$HARNESS_CLAUDE_MCP_CONFIG" > "$mcp_config_path"; '
            "unset HARNESS_CLAUDE_MCP_CONFIG; "
            'set -- "$@" --mcp-config "$mcp_config_path"; '
            "fi; "
            "trap '[ -z \"$mcp_config_path\" ] || "
            "rm -f -- \"$mcp_config_path\"' EXIT; "
            "while IFS= read -r line; do "
            'if [ "$line" = "$input_marker" ]; then break; fi; '
            'printf "%s\\n" "$line"; '
            'done | "$@"'
        )
        wrapped_argv = [
            "bash",
            "-o",
            "pipefail",
            "-c",
            stdin_wrapper,
            "harness-stdin",
            environment_marker,
            argument_marker,
            self._end_input_marker,
        ]
        command = f"cd {shlex.quote(cwd)} && {shlex.join(wrapped_argv)}"
        response = await self._sandbox.process.execute_session_command(
            self._session_id,
            SessionExecuteRequest(
                command=command,
                run_async=True,
                suppress_input_echo=True,
            ),
        )
        self._command_id = response.cmd_id
        environment_lines.append(environment_marker)
        environment_lines.extend(argument_lines)
        environment_lines.append(argument_marker)
        await self._sandbox.process.send_session_command_input(
            self._session_id,
            self._command_id,
            "\n".join(environment_lines) + "\n",
        )
        self._logs_task = asyncio.create_task(self._stream_logs())

    async def _stream_logs(self) -> None:
        assert self._command_id is not None

        async def stdout(chunk: str) -> None:
            await self._stdout.put(chunk.encode("utf-8"))

        async def stderr(chunk: str) -> None:
            await self._stderr.put(chunk.encode("utf-8"))

        try:
            await self._sandbox.process.get_session_command_logs_async(
                self._session_id, self._command_id, stdout, stderr
            )
        finally:
            await self._stdout.put(None)
            await self._stderr.put(None)

    async def write(self, data: str) -> None:
        if self._command_id is None:
            raise RuntimeError("remote Claude command is not started")
        await self._sandbox.process.send_session_command_input(
            self._session_id, self._command_id, data
        )

    async def end_input(self) -> None:
        if self._command_id is not None:
            await self._sandbox.process.send_session_command_input(
                self._session_id,
                self._command_id,
                f"{self._end_input_marker}\n",
            )

    async def read_stdout(self) -> bytes | None:
        return await self._stdout.get()

    async def read_stderr(self) -> bytes | None:
        return await self._stderr.get()

    async def wait(self) -> int:
        if self._logs_task is not None:
            await self._logs_task
        if self._command_id is None:
            return 1
        command = await self._sandbox.process.get_session_command(
            self._session_id, self._command_id
        )
        return command.exit_code if command.exit_code is not None else 1

    async def terminate(self) -> None:
        await self._sandbox.process.delete_session(self._session_id)


class SdkDaytonaRemoteSandbox:
    def __init__(self, sandbox: AsyncSandbox) -> None:
        self._sandbox = sandbox
        self.id = sandbox.id

    async def ensure_claude_cli(self, *, version: str, path: str) -> None:
        quoted_path = shlex.quote(path)
        expected = f"{version} (Claude Code)"
        check = await self._sandbox.process.exec(f"{quoted_path} --version")
        if check.exit_code == 0 and check.result.strip() == expected:
            return
        installer = (
            "set -o pipefail; "
            "curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors "
            "https://claude.ai/install.sh | bash -s "
            f"{shlex.quote(version)}"
        )
        installed = await self._sandbox.process.exec(
            f"bash -lc {shlex.quote(installer)}", timeout=180
        )
        if installed.exit_code != 0:
            raise RuntimeError("failed to install the pinned Claude CLI in Daytona")
        verified = await self._sandbox.process.exec(f"{quoted_path} --version")
        if verified.exit_code != 0 or verified.result.strip() != expected:
            raise RuntimeError("Daytona Claude CLI version verification failed")

    async def create_folder(self, path: str) -> None:
        response = await self._sandbox.process.exec(
            f"mkdir -p -- {shlex.quote(path)}"
        )
        if response.exit_code != 0:
            raise RuntimeError("failed to create Daytona workspace directory")

    async def upload(self, remote_path: str, content: bytes) -> None:
        await self._sandbox.fs.upload_file(content, remote_path)

    async def list_files(
        self, remote_path: str
    ) -> list[tuple[str, bool, int | None]]:
        files = await self._sandbox.fs.list_files(remote_path, depth=100)
        return [
            (
                file.path or str(PurePosixPath(remote_path) / file.name),
                file.is_dir,
                file.size if file.size >= 0 else None,
            )
            for file in files
        ]

    async def download(self, remote_path: str) -> bytes:
        return await self._sandbox.fs.download_file(remote_path)

    def remote_session(self) -> RemoteClaudeSession:
        return SdkDaytonaRemoteSession(self._sandbox)

    @property
    def sdk_sandbox(self) -> AsyncSandbox:
        return self._sandbox


class SdkDaytonaClient:
    def __init__(self, sdk: AsyncDaytona) -> None:
        self._sdk = sdk

    @classmethod
    def from_config(
        cls, *, api_key: str, api_url: str | None = None, target: str | None = None
    ) -> SdkDaytonaClient:
        configure_default_ca_bundle()
        return cls(
            AsyncDaytona(
                DaytonaConfig(api_key=api_key, api_url=api_url, target=target)
            )
        )

    async def create(self, **parameters: Any) -> DaytonaRemoteSandbox:
        sandbox = await self._sdk.create(
            CreateSandboxFromSnapshotParams.model_validate(parameters)
        )
        return SdkDaytonaRemoteSandbox(sandbox)

    async def get(self, sandbox_id: str) -> DaytonaRemoteSandbox:
        return SdkDaytonaRemoteSandbox(await self._sdk.get(sandbox_id))

    async def start(self, sandbox: DaytonaRemoteSandbox) -> None:
        await self._sdk.start(cast(SdkDaytonaRemoteSandbox, sandbox).sdk_sandbox)

    async def stop(self, sandbox: DaytonaRemoteSandbox) -> None:
        await self._sdk.stop(cast(SdkDaytonaRemoteSandbox, sandbox).sdk_sandbox)

    async def delete(self, sandbox: DaytonaRemoteSandbox) -> None:
        await self._sdk.delete(cast(SdkDaytonaRemoteSandbox, sandbox).sdk_sandbox)


class DaytonaSandboxProvider:
    def __init__(
        self,
        *,
        client: DaytonaClient,
        local_root: Path | None = None,
        snapshot: str | None = None,
        remote_workspace_root: str = "/home/daytona/harness",
        cli_version: str = "2.1.206",
        cli_path: str = "/home/daytona/.local/bin/claude",
        delete_on_destroy: bool = False,
        auto_stop_interval_minutes: int = 15,
        auto_delete_interval_minutes: int = 60,
        max_collect_bytes: int = 512 * 1024 * 1024,
        max_collect_members: int = 10_000,
    ) -> None:
        if max_collect_bytes <= 0 or max_collect_members <= 0:
            raise ValueError("Daytona collection limits must be positive")
        self._client = client
        self._local_root = local_root
        self._snapshot = snapshot
        self._remote_workspace_root = remote_workspace_root.rstrip("/")
        self._cli_version = cli_version
        self._cli_path = cli_path
        self._delete_on_destroy = delete_on_destroy
        self._auto_stop_interval_minutes = auto_stop_interval_minutes
        self._auto_delete_interval_minutes = auto_delete_interval_minutes
        self._max_collect_bytes = max_collect_bytes
        self._max_collect_members = max_collect_members
        self._sandboxes: dict[str, tuple[DaytonaRemoteSandbox, bool]] = {}

    async def provision(self, run: Run) -> SandboxHandle:
        existing = run.input.get("daytona_sandbox_id")
        if isinstance(existing, str) and existing:
            sandbox = await self._client.get(existing)
            await self._client.start(sandbox)
            owned = False
        else:
            sandbox = await self._client.create(
                snapshot=self._snapshot,
                name=f"harness-{run.run_id}-{run.fencing_token}"[:64],
                labels={
                    "harness.tenant": run.tenant_id,
                    "harness.session": run.session_id,
                    "harness.run": run.run_id,
                },
                auto_stop_interval=self._auto_stop_interval_minutes,
                auto_delete_interval=(
                    self._auto_delete_interval_minutes
                    if self._delete_on_destroy
                    else None
                ),
            )
            owned = True
        path = Path(
            tempfile.mkdtemp(prefix=f"{run.run_id}-", dir=self._local_root)
        )
        remote_workspace = f"{self._remote_workspace_root}/{run.run_id}"
        self._sandboxes[sandbox.id] = (sandbox, owned)

        def transport_factory(raw_options: object) -> object:
            options = cast(ClaudeAgentOptions, raw_options)
            return DaytonaClaudeTransport(
                session=sandbox.remote_session(),
                options=options,
                remote_workspace=remote_workspace,
                cli_path=self._cli_path,
            )

        return SandboxHandle(
            sandbox_id=sandbox.id,
            path=path,
            provider="daytona",
            isolation_level=SandboxIsolation.CONTAINER,
            remote_workspace=remote_workspace,
            runtime_transport_factory=transport_factory,
        )

    async def prepare(self, handle: SandboxHandle) -> None:
        sandbox, _ = self._sandboxes[handle.sandbox_id]
        assert handle.remote_workspace is not None
        await sandbox.ensure_claude_cli(
            version=self._cli_version,
            path=self._cli_path,
        )
        await sandbox.create_folder(handle.remote_workspace)
        for path in sorted(handle.path.rglob("*")):
            relative = path.relative_to(handle.path).as_posix()
            remote = f"{handle.remote_workspace}/{relative}"
            if path.is_dir():
                await sandbox.create_folder(remote)
            elif path.is_file() and not path.is_symlink():
                await sandbox.upload(remote, path.read_bytes())

    async def collect(self, handle: SandboxHandle) -> None:
        sandbox, _ = self._sandboxes[handle.sandbox_id]
        assert handle.remote_workspace is not None
        remote_files = await sandbox.list_files(handle.remote_workspace)
        if len(remote_files) > self._max_collect_members:
            raise ValueError("Daytona workspace exceeds collection member limit")
        declared_size = sum(
            size for _, is_dir, size in remote_files if not is_dir and size is not None
        )
        if declared_size > self._max_collect_bytes:
            raise ValueError("Daytona workspace exceeds collection size limit")
        collected_size = 0
        for remote_path, is_dir, _ in remote_files:
            relative = PurePosixPath(remote_path).relative_to(
                PurePosixPath(handle.remote_workspace)
            )
            if ".." in relative.parts:
                raise ValueError("Daytona workspace path escaped local collection root")
            local = handle.path.joinpath(*relative.parts)
            if is_dir:
                local.mkdir(parents=True, exist_ok=True)
            else:
                content = await sandbox.download(remote_path)
                collected_size += len(content)
                if collected_size > self._max_collect_bytes:
                    raise ValueError("Daytona workspace exceeds collection size limit")
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(content)

    async def execute(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = 30,
    ) -> SandboxCommandResult:
        if not argv:
            raise ValueError("sandbox command argv must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("sandbox command timeout must be positive")
        sandbox, _ = self._sandboxes[handle.sandbox_id]
        if handle.remote_workspace is None:
            raise ValueError("Daytona command requires a remote workspace")
        session = sandbox.remote_session()
        await session.start(list(argv), handle.remote_workspace, dict(environment or {}))
        try:
            await session.end_input()

            async def read(stream: str) -> bytes:
                chunks: list[bytes] = []
                reader = session.read_stdout if stream == "stdout" else session.read_stderr
                while (chunk := await reader()) is not None:
                    chunks.append(chunk)
                return b"".join(chunks)

            stdout, stderr, exit_code = await asyncio.wait_for(
                asyncio.gather(read("stdout"), read("stderr"), session.wait()),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            raise
        finally:
            await session.terminate()
        return SandboxCommandResult(
            exit_code=exit_code,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    async def destroy(self, handle: SandboxHandle) -> None:
        entry = self._sandboxes.pop(handle.sandbox_id, None)
        if entry is not None:
            sandbox, owned = entry
            await self._client.stop(sandbox)
            if self._delete_on_destroy and owned:
                await self._client.delete(sandbox)
        shutil.rmtree(handle.path, ignore_errors=True)
