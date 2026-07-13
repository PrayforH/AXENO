"""Daytona SandboxProvider plus adapters for the official async SDK."""

from __future__ import annotations

import asyncio
import shlex
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast
from uuid import uuid4

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
from harness.sandbox.base import SandboxHandle


class DaytonaRemoteSandbox(Protocol):
    id: str

    async def create_folder(self, path: str) -> None: ...

    async def upload(self, remote_path: str, content: bytes) -> None: ...

    async def list_files(self, remote_path: str) -> list[tuple[str, bool]]: ...

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
        self._command_id: str | None = None
        self._stdout: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._stderr: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._logs_task: asyncio.Task[None] | None = None

    async def start(self, argv: list[str], cwd: str, env: dict[str, str]) -> None:
        await self._sandbox.process.create_session(self._session_id)
        environment = " ".join(
            f"{key}={shlex.quote(value)}" for key, value in sorted(env.items())
        )
        command = f"cd {shlex.quote(cwd)} && env {environment} {shlex.join(argv)}"
        response = await self._sandbox.process.execute_session_command(
            self._session_id,
            SessionExecuteRequest(command=command, run_async=True),
        )
        self._command_id = response.cmd_id
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
                self._session_id, self._command_id, "\x04"
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

    async def create_folder(self, path: str) -> None:
        response = await self._sandbox.process.exec(
            f"mkdir -p -- {shlex.quote(path)}"
        )
        if response.exit_code != 0:
            raise RuntimeError("failed to create Daytona workspace directory")

    async def upload(self, remote_path: str, content: bytes) -> None:
        await self._sandbox.fs.upload_file(content, remote_path)

    async def list_files(self, remote_path: str) -> list[tuple[str, bool]]:
        files = await self._sandbox.fs.list_files(remote_path, depth=100)
        return [
            (file.path or str(PurePosixPath(remote_path) / file.name), file.is_dir)
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
        remote_workspace_root: str = "/workspace/harness",
        cli_version: str = "2.1.206",
        delete_on_destroy: bool = False,
    ) -> None:
        self._client = client
        self._local_root = local_root
        self._snapshot = snapshot
        self._remote_workspace_root = remote_workspace_root.rstrip("/")
        self._cli_version = cli_version
        self._delete_on_destroy = delete_on_destroy
        self._sandboxes: dict[str, DaytonaRemoteSandbox] = {}

    async def provision(self, run: Run) -> SandboxHandle:
        existing = run.input.get("daytona_sandbox_id")
        if isinstance(existing, str) and existing:
            sandbox = await self._client.get(existing)
            await self._client.start(sandbox)
        else:
            sandbox = await self._client.create(
                snapshot=self._snapshot,
                name=f"harness-{run.run_id}"[:64],
                labels={
                    "harness.tenant": run.tenant_id,
                    "harness.session": run.session_id,
                    "harness.run": run.run_id,
                },
                auto_stop_interval=0,
            )
        path = Path(
            tempfile.mkdtemp(prefix=f"{run.run_id}-", dir=self._local_root)
        )
        remote_workspace = f"{self._remote_workspace_root}/{run.run_id}"
        self._sandboxes[sandbox.id] = sandbox

        def transport_factory(raw_options: object) -> object:
            options = cast(ClaudeAgentOptions, raw_options)
            return DaytonaClaudeTransport(
                session=sandbox.remote_session(),
                options=options,
                remote_workspace=remote_workspace,
                cli_version=self._cli_version,
            )

        return SandboxHandle(
            sandbox_id=sandbox.id,
            path=path,
            provider="daytona",
            remote_workspace=remote_workspace,
            runtime_transport_factory=transport_factory,
        )

    async def prepare(self, handle: SandboxHandle) -> None:
        sandbox = self._sandboxes[handle.sandbox_id]
        assert handle.remote_workspace is not None
        await sandbox.create_folder(handle.remote_workspace)
        for path in sorted(handle.path.rglob("*")):
            relative = path.relative_to(handle.path).as_posix()
            remote = f"{handle.remote_workspace}/{relative}"
            if path.is_dir():
                await sandbox.create_folder(remote)
            elif path.is_file() and not path.is_symlink():
                await sandbox.upload(remote, path.read_bytes())

    async def collect(self, handle: SandboxHandle) -> None:
        sandbox = self._sandboxes[handle.sandbox_id]
        assert handle.remote_workspace is not None
        for remote_path, is_dir in await sandbox.list_files(handle.remote_workspace):
            relative = PurePosixPath(remote_path).relative_to(
                PurePosixPath(handle.remote_workspace)
            )
            if ".." in relative.parts:
                raise ValueError("Daytona workspace path escaped local collection root")
            local = handle.path.joinpath(*relative.parts)
            if is_dir:
                local.mkdir(parents=True, exist_ok=True)
            else:
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(await sandbox.download(remote_path))

    async def destroy(self, handle: SandboxHandle) -> None:
        sandbox = self._sandboxes.pop(handle.sandbox_id, None)
        if sandbox is not None:
            await self._client.stop(sandbox)
            if self._delete_on_destroy:
                await self._client.delete(sandbox)
        shutil.rmtree(handle.path, ignore_errors=True)
