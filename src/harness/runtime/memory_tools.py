"""Task-local Claude SDK tool for durable user-memory updates."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

from harness.application.memory import UserMemoryService
from harness.core.errors import ConflictError
from harness.core.models import ExecutionIdentity

type MemoryExecution = tuple[UserMemoryService, ExecutionIdentity]
_memory_execution: ContextVar[MemoryExecution | None] = ContextVar(
    "harness_memory_execution", default=None
)


@contextmanager
def memory_execution_context(
    service: UserMemoryService, identity: ExecutionIdentity
) -> Generator[None]:
    token = _memory_execution.set((service, identity))
    try:
        yield
    finally:
        _memory_execution.reset(token)


async def _update_user_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    execution = _memory_execution.get()
    if execution is None:
        raise RuntimeError("memory execution context is not active")
    content = arguments.get("content")
    expected = arguments.get("expected_version")
    if not isinstance(content, str) or not content.strip():
        return {
            "content": [{"type": "text", "text": "content must be a non-empty string"}],
            "isError": True,
        }
    if expected is not None and (not isinstance(expected, int) or isinstance(expected, bool)):
        return {
            "content": [{"type": "text", "text": "expected_version must be an integer"}],
            "isError": True,
        }
    service, identity = execution
    try:
        saved = await service.update(
            identity,
            content,
            expected_version=expected,
        )
    except (ValueError, ConflictError) as error:
        return {
            "content": [{"type": "text", "text": str(error)}],
            "isError": True,
        }
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"version": saved.version}, separators=(",", ":")),
            }
        ]
    }


update_user_memory_tool = SdkMcpTool(
    name="update_user_memory",
    description="Replace durable preferences or facts remembered for this user and agent.",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "expected_version": {"type": "integer", "minimum": 0},
        },
        "required": ["content"],
        "additionalProperties": False,
    },
    handler=_update_user_memory,
)


def create_memory_mcp_server() -> McpSdkServerConfig:
    return create_sdk_mcp_server("harness-memory", tools=[update_user_memory_tool])
