"""Sandbox lifecycle contract."""

from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from harness.core.models import Run


class SandboxIsolation(StrEnum):
    WORKSPACE = "workspace"
    CONTAINER = "container"


class SandboxHandle(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    sandbox_id: str
    path: Path
    provider: str = "local"
    isolation_level: SandboxIsolation = SandboxIsolation.WORKSPACE
    remote_workspace: str | None = None
    runtime_transport_factory: Callable[[object], object] | None = Field(
        default=None, exclude=True, repr=False
    )
    deferred_tool_execution: bool = Field(default=False, exclude=True)


class SandboxCommandResult(BaseModel):
    """Bounded command result without command arguments or environment secrets."""

    model_config = ConfigDict(frozen=True)

    exit_code: int
    stdout: str = ""
    stderr: str = ""


class SandboxProvider(Protocol):
    async def provision(self, run: Run) -> SandboxHandle: ...

    async def prepare(self, handle: SandboxHandle) -> None: ...

    async def execute(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = 30,
    ) -> SandboxCommandResult: ...

    async def collect(self, handle: SandboxHandle) -> None: ...

    async def destroy(self, handle: SandboxHandle) -> None: ...
