"""Sandbox lifecycle contract."""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from harness.core.models import Run


class SandboxHandle(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox_id: str
    path: Path


class SandboxProvider(Protocol):
    async def provision(self, run: Run) -> SandboxHandle: ...

    async def destroy(self, handle: SandboxHandle) -> None: ...

