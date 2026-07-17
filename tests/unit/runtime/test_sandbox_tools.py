from collections.abc import Mapping, Sequence

import pytest

from harness.runtime.sandbox_tools import (
    canonical_tool_name,
    create_sandbox_tool,
    proxy_tool_name,
)
from harness.sandbox.base import SandboxCommandResult


def test_proxy_tool_names_round_trip_to_builtin_names() -> None:
    assert proxy_tool_name("Read") == "mcp__harness-sandbox__read"
    assert canonical_tool_name("mcp__harness-sandbox__write") == "Write"
    assert canonical_tool_name("mcp__tavily__search") == "mcp__tavily__search"


@pytest.mark.asyncio
async def test_bash_proxy_delegates_to_isolated_executor_with_bounded_timeout() -> None:
    calls: list[tuple[Sequence[str], Mapping[str, str] | None, float]] = []

    async def execute(
        argv: Sequence[str],
        environment: Mapping[str, str] | None,
        timeout_seconds: float,
    ) -> SandboxCommandResult:
        calls.append((argv, environment, timeout_seconds))
        return SandboxCommandResult(exit_code=0, stdout="ok")

    tool = create_sandbox_tool(
        builtin="Bash",
        description="test",
        schema={},
        executor=execute,
    )

    result = await tool.handler({"command": "pwd", "timeout": 500_000})

    assert calls == [(("bash", "-lc", "pwd"), None, 120.0)]
    assert result["content"] == [{"type": "text", "text": "ok"}]
    assert "isError" not in result


@pytest.mark.asyncio
async def test_file_proxy_uses_argument_vector_and_reports_backend_failure() -> None:
    calls: list[Sequence[str]] = []

    async def execute(
        argv: Sequence[str],
        _environment: Mapping[str, str] | None,
        _timeout_seconds: float,
    ) -> SandboxCommandResult:
        calls.append(argv)
        return SandboxCommandResult(exit_code=2, stderr="path escaped workspace")

    tool = create_sandbox_tool(
        builtin="Read",
        description="test",
        schema={},
        executor=execute,
    )

    result = await tool.handler({"file_path": "../secret"})

    assert calls[0][:2] == ("python3", "-c")
    assert calls[0][-2] == "read"
    assert result["isError"] is True
    assert result["content"] == [
        {"type": "text", "text": "path escaped workspace"}
    ]
