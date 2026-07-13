import asyncio

import pytest
from claude_agent_sdk import ClaudeAgentOptions

from harness.runtime.daytona_transport import (
    DaytonaClaudeTransport,
    DaytonaTransportError,
    build_remote_claude_command,
)


class FakeRemoteSession:
    def __init__(
        self,
        stdout: list[bytes | None],
        *,
        stderr: list[bytes | None] | None = None,
        exit_code: int = 0,
        hang_terminate: bool = False,
    ) -> None:
        self.stdout = asyncio.Queue[bytes | None]()
        self.stderr = asyncio.Queue[bytes | None]()
        for chunk in stdout:
            self.stdout.put_nowait(chunk)
        for chunk in stderr or [None]:
            self.stderr.put_nowait(chunk)
        self.exit_code = exit_code
        self.hang_terminate = hang_terminate
        self.started: tuple[list[str], str, dict[str, str]] | None = None
        self.writes: list[str] = []
        self.ended = False
        self.terminated = False

    async def start(self, argv: list[str], cwd: str, env: dict[str, str]) -> None:
        self.started = (argv, cwd, env)

    async def write(self, data: str) -> None:
        self.writes.append(data)

    async def end_input(self) -> None:
        self.ended = True

    async def read_stdout(self) -> bytes | None:
        return await self.stdout.get()

    async def read_stderr(self) -> bytes | None:
        return await self.stderr.get()

    async def wait(self) -> int:
        return self.exit_code

    async def terminate(self) -> None:
        self.terminated = True
        if self.hang_terminate:
            await asyncio.Event().wait()


def options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        tools=["Read", "Bash"],
        allowed_tools=["Read"],
        system_prompt="Act carefully",
        model="gateway-model",
        max_turns=8,
        permission_mode="dontAsk",
        include_partial_messages=True,
        strict_mcp_config=True,
        env={"ANTHROPIC_BASE_URL": "https://gateway.example"},
    )


def test_command_uses_native_cli_and_contains_required_streaming_flags() -> None:
    command = build_remote_claude_command(
        options(), cli_path="/home/daytona/.local/bin/claude"
    )

    assert command[0] == "/home/daytona/.local/bin/claude"
    assert command[-2:] == ["--input-format", "stream-json"]
    assert command[command.index("--model") + 1] == "gateway-model"
    assert command[command.index("--tools") + 1] == "Read,Bash"
    assert "--include-partial-messages" in command
    assert "--strict-mcp-config" in command


@pytest.mark.asyncio
async def test_transport_frames_fragmented_ndjson_and_skips_diagnostics() -> None:
    session = FakeRemoteSession(
        [
            b"install notice\n{\"type\":\"system\",\"sub",
            b"type\":\"init\"}\n{\"type\":\"result\",\"ok\":true}\n",
            None,
        ],
        stderr=[b"stderr diagnostic", None],
    )
    transport = DaytonaClaudeTransport(
        session=session,
        options=options(),
        remote_workspace="/workspace/run-a",
        cli_path="/home/daytona/.local/bin/claude",
    )

    await transport.connect()
    await transport.write('{"type":"user"}\n')
    messages = [message async for message in transport.read_messages()]
    await transport.end_input()
    await transport.close()

    assert messages == [
        {"type": "system", "subtype": "init"},
        {"type": "result", "ok": True},
    ]
    assert session.started is not None
    assert session.started[1] == "/workspace/run-a"
    assert session.writes == ['{"type":"user"}\n']
    assert session.ended is True


@pytest.mark.asyncio
async def test_transport_reports_remote_exit_without_exposing_stderr() -> None:
    session = FakeRemoteSession(
        [None], stderr=[b"ANTHROPIC_AUTH_TOKEN=private", None], exit_code=17
    )
    transport = DaytonaClaudeTransport(
        session=session,
        options=options(),
        remote_workspace="/workspace/run-a",
        cli_path="/home/daytona/.local/bin/claude",
    )
    await transport.connect()

    with pytest.raises(DaytonaTransportError, match="code 17") as captured:
        async for _message in transport.read_messages():
            pass

    assert "private" not in str(captured.value)


@pytest.mark.asyncio
async def test_close_is_bounded_even_if_remote_termination_hangs() -> None:
    session = FakeRemoteSession([None], hang_terminate=True)
    transport = DaytonaClaudeTransport(
        session=session,
        options=options(),
        remote_workspace="/workspace/run-a",
        cli_path="/home/daytona/.local/bin/claude",
        close_timeout=0.01,
    )
    await transport.connect()

    await asyncio.wait_for(transport.close(), timeout=0.2)

    assert session.terminated is True
    assert transport.is_ready() is False
