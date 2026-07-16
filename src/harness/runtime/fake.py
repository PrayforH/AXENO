"""Deterministic runtime used for tests and local infrastructure validation."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from harness.runtime.base import RuntimeContext, RuntimeEvent


class FakeRuntime:
    def __init__(
        self,
        *,
        fail: bool = False,
        delay: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._fail = fail
        self._delay = delay
        self.execution_count = 0

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        self.execution_count += 1
        if self._fail:
            raise RuntimeError("configured fake runtime failure")
        prompt = str(context.run.input.get("prompt", ""))
        yield RuntimeEvent(type="message.start", payload={"role": "assistant"})
        if "[slow]" in prompt:
            await self._delay(3.0)
        yield RuntimeEvent(type="message.delta", payload={"text": f"Echo: {prompt}"})
        if "[approval]" in prompt:
            yield RuntimeEvent(
                type="tool.request",
                payload={
                    "tool_call_id": "fake-write-1",
                    "name": "Write",
                    "arguments": {"file_path": "output/result.txt"},
                },
            )
        if "[artifact]" in prompt:
            output = context.workspace / "output" / "result.txt"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("fake runtime artifact")
            yield RuntimeEvent(
                type="artifact.output",
                payload={
                    "path": "output/result.txt",
                    "name": "result.txt",
                    "media_type": "text/plain",
                },
            )
        yield RuntimeEvent(type="message.completed", payload={"role": "assistant"})
