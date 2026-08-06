"""Task-local Claude SDK tool for consent-gated memory proposals."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

from harness.core.errors import ConflictError
from harness.core.models import ExecutionIdentity
from harness.memory_bank.service import MemoryBankService

type MemoryExecution = tuple[MemoryBankService, ExecutionIdentity]
_memory_execution: ContextVar[MemoryExecution | None] = ContextVar(
    "harness_memory_execution", default=None
)


@contextmanager
def memory_execution_context(
    service: MemoryBankService, identity: ExecutionIdentity
) -> Generator[None]:
    token = _memory_execution.set((service, identity))
    try:
        yield
    finally:
        _memory_execution.reset(token)


async def _propose_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    execution = _memory_execution.get()
    if execution is None:
        raise RuntimeError("memory execution context is not active")
    content = arguments.get("content")
    if not isinstance(content, str) or not content.strip():
        return {
            "content": [{"type": "text", "text": "content must be a non-empty string"}],
            "isError": True,
        }
    service, identity = execution
    try:
        saved = await service.propose_agent(identity, content)
    except (ValueError, ConflictError) as error:
        return {
            "content": [{"type": "text", "text": str(error)}],
            "isError": True,
        }
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "entryId": saved.entry_id,
                        "status": saved.status.value,
                        "requiresConfirmation": saved.status.value == "pending",
                    },
                    separators=(",", ":"),
                ),
            }
        ]
    }


propose_memory_tool = SdkMcpTool(
    name="propose_memory",
    description=(
        "Propose a preference or durable fact for the user to confirm. "
        "The proposal is not active unless user consent or an explicit policy allows it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
        },
        "required": ["content"],
        "additionalProperties": False,
    },
    handler=_propose_memory,
)

# Compatibility export for callers importing the previous symbol. The MCP tool name and
# semantics are intentionally changed to proposal-only.
update_user_memory_tool = propose_memory_tool


def create_memory_mcp_server() -> McpSdkServerConfig:
    return create_sdk_mcp_server("harness-memory", tools=[propose_memory_tool])
