"""Deterministic runtime used for tests and local infrastructure validation."""

from collections.abc import AsyncIterator

from harness.runtime.base import RuntimeContext, RuntimeEvent


class FakeRuntime:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.execution_count = 0

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        self.execution_count += 1
        if self._fail:
            raise RuntimeError("configured fake runtime failure")
        prompt = str(context.run.input.get("prompt", ""))
        yield RuntimeEvent(type="message.start", payload={"role": "assistant"})
        yield RuntimeEvent(type="message.delta", payload={"text": f"Echo: {prompt}"})
        yield RuntimeEvent(type="message.completed", payload={"role": "assistant"})
