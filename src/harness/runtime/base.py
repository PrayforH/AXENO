"""Runtime contract independent from a specific Agent SDK."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from harness.core.models import Run, Session


class RuntimeContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    run: Run
    session: Session
    workspace: Path
    input_files: tuple[str, ...] = ()


class RuntimeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRuntime(Protocol):
    def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]: ...
