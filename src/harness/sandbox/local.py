"""Local temporary-directory Sandbox implementation."""

import shutil
import tempfile
from pathlib import Path

from harness.core.models import Run
from harness.sandbox.base import SandboxHandle


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

