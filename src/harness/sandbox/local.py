"""Local temporary-directory Sandbox implementation."""

import asyncio
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from harness.core.models import Run
from harness.sandbox.base import SandboxCommandResult, SandboxHandle


class LocalSandboxProvider:
    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)

    async def provision(self, run: Run) -> SandboxHandle:
        path = Path(tempfile.mkdtemp(prefix=f"{run.run_id}-", dir=self._root))
        return SandboxHandle(sandbox_id=path.name, path=path)

    async def destroy(self, handle: SandboxHandle) -> None:
        shutil.rmtree(handle.path, ignore_errors=True)

    async def prepare(self, handle: SandboxHandle) -> None:
        del handle

    async def execute(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = 30,
    ) -> SandboxCommandResult:
        if not argv:
            raise ValueError("sandbox command argv must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("sandbox command timeout must be positive")
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=handle.path,
            env={**os.environ, **dict(environment or {})},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        return SandboxCommandResult(
            exit_code=process.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    async def collect(self, handle: SandboxHandle) -> None:
        del handle
