from typing import Any

from claude_agent_sdk import SdkMcpTool


async def _empty_result(_arguments: dict[str, Any]) -> dict[str, Any]:
    return {"content": []}


lookup_tool = SdkMcpTool(
    name="lookup_customer",
    description="Look up one customer",
    input_schema={"type": "object", "properties": {"customer_id": {"type": "string"}}},
    handler=_empty_result,
)

summarize_tool = SdkMcpTool(
    name="summarize_account",
    description="Summarize one account",
    input_schema={"type": "object", "properties": {"account_id": {"type": "string"}}},
    handler=_empty_result,
)

tool_list = [lookup_tool, summarize_tool]
duplicate_tools = [lookup_tool, lookup_tool]
not_a_tool = object()

