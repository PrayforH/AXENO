"""Claude Agent SDK transport that runs the Claude CLI inside Daytona."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol, cast

import anyio
from claude_agent_sdk import ClaudeAgentOptions, Transport


class DaytonaTransportError(RuntimeError):
    """Remote Claude process failed without forwarding sensitive diagnostics."""


class RemoteClaudeSession(Protocol):
    async def start(self, argv: list[str], cwd: str, env: dict[str, str]) -> None: ...

    async def write(self, data: str) -> None: ...

    async def end_input(self) -> None: ...

    async def read_stdout(self) -> bytes | None: ...

    async def read_stderr(self) -> bytes | None: ...

    async def wait(self) -> int: ...

    async def terminate(self) -> None: ...


def _mcp_config(options: ClaudeAgentOptions) -> str | None:
    if not options.mcp_servers:
        return None
    if isinstance(options.mcp_servers, (str, Path)):
        return str(options.mcp_servers)
    servers: dict[str, object] = {}
    for name, raw in options.mcp_servers.items():
        if raw.get("type") == "sdk":
            serialized = dict(raw)
            serialized.pop("instance", None)
            servers[name] = serialized
        else:
            servers[name] = raw
    return json.dumps({"mcpServers": servers}, separators=(",", ":"))


def build_remote_claude_command(
    options: ClaudeAgentOptions, *, cli_path: str
) -> list[str]:
    if not cli_path or any(character.isspace() for character in cli_path):
        raise ValueError("an absolute Claude CLI path is required")
    command = [
        cli_path,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if isinstance(options.system_prompt, str):
        command.extend(["--system-prompt", options.system_prompt])
    if isinstance(options.tools, list):
        command.extend(["--tools", ",".join(options.tools)])
    if options.allowed_tools:
        command.extend(["--allowedTools", ",".join(options.allowed_tools)])
    if options.max_turns:
        command.extend(["--max-turns", str(options.max_turns)])
    if options.max_budget_usd is not None:
        command.extend(["--max-budget-usd", str(options.max_budget_usd)])
    if options.model:
        command.extend(["--model", options.model])
    if options.permission_mode:
        command.extend(["--permission-mode", options.permission_mode])
    if options.resume:
        command.extend(["--resume", options.resume])
    mcp_config = _mcp_config(options)
    if mcp_config is not None:
        command.extend(["--mcp-config", mcp_config])
    if options.include_partial_messages:
        command.append("--include-partial-messages")
    if options.strict_mcp_config:
        command.append("--strict-mcp-config")
    if options.skills is not None:
        command.append("--setting-sources=user,project")
    command.extend(["--input-format", "stream-json"])
    return command


class DaytonaClaudeTransport(Transport):
    def __init__(
        self,
        *,
        session: RemoteClaudeSession,
        options: ClaudeAgentOptions,
        remote_workspace: str,
        cli_path: str,
        close_timeout: float = 5.0,
    ) -> None:
        self._session = session
        self._options = options
        self._remote_workspace = remote_workspace
        self._cli_path = cli_path
        self._close_timeout = close_timeout
        self._ready = False
        self._stderr_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        if self._ready:
            return
        environment = {
            **self._options.env,
            "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
        }
        await self._session.start(
            build_remote_claude_command(
                self._options, cli_path=self._cli_path
            ),
            self._remote_workspace,
            environment,
        )
        self._ready = True
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        while await self._session.read_stderr() is not None:
            pass

    async def write(self, data: str) -> None:
        if not self._ready:
            raise DaytonaTransportError("remote Claude transport is not connected")
        await self._session.write(data)

    async def end_input(self) -> None:
        if self._ready:
            await self._session.end_input()

    async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        buffer = ""
        while True:
            chunk = await self._session.read_stdout()
            if chunk is None:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                parsed = self._parse_line(line)
                if parsed is not None:
                    yield parsed
        parsed = self._parse_line(buffer)
        if parsed is not None:
            yield parsed
        exit_code = await self._session.wait()
        if exit_code != 0:
            raise DaytonaTransportError(
                f"remote Claude CLI exited with code {exit_code}"
            )

    @staticmethod
    def _parse_line(line: str) -> dict[str, Any] | None:
        stripped = line.strip()
        if not stripped:
            return None
        try:
            value: object = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(value, dict):
            return None
        return cast(dict[str, Any], value)

    async def close(self) -> None:
        self._ready = False
        with anyio.move_on_after(self._close_timeout):
            await self._session.terminate()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            with anyio.move_on_after(self._close_timeout):
                try:
                    await self._stderr_task
                except asyncio.CancelledError:
                    pass
            self._stderr_task = None

    def is_ready(self) -> bool:
        return self._ready
