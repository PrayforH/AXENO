"""Opt-in live smoke test for a new-api Anthropic-compatible gateway."""

import asyncio
import os
from pathlib import Path

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, query

from harness.runtime.message_mapper import map_sdk_message


async def main() -> int:
    base_url = os.getenv("NEW_API_BASE_URL", "")
    api_key = os.getenv("NEW_API_KEY", "")
    model = os.getenv("NEW_API_MODEL", "")
    if not all((base_url, api_key, model)):
        print("SKIP: set NEW_API_BASE_URL, NEW_API_KEY and NEW_API_MODEL to run live smoke")
        return 0

    options = ClaudeAgentOptions(
        model=model,
        cwd=Path.cwd(),
        tools=["Read", "Task"],
        allowed_tools=["Read", "Task"],
        permission_mode="dontAsk",
        include_partial_messages=True,
        max_turns=6,
        agents={
            "helper": AgentDefinition(
                description="Summarizes a short text passed by the parent Agent",
                prompt="Return a one-sentence factual summary.",
                tools=[],
                model="inherit",
            )
        },
        env={
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_AUTH_TOKEN": api_key,
            "CLAUDE_AGENT_SDK_CLIENT_APP": "claude-agent-harness-smoke/0.1.0",
        },
    )
    seen: set[str] = set()
    prompt = (
        "Read pyproject.toml, state the project name, then delegate a one-sentence "
        "summary of that name to the helper subagent. Keep the final answer short."
    )
    async for message in query(prompt=prompt, options=options):
        for event in map_sdk_message(message):
            seen.add(event.type)
            print(event.type)

    required = {"message.delta", "tool.request", "runtime.result"}
    missing = required - seen
    if missing:
        raise RuntimeError(f"new-api smoke missing expected events: {sorted(missing)}")
    print("new-api smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
