"""Portable archive and restore for session workspaces."""

import asyncio
import hashlib
import tarfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from harness.core.models import WorkspaceSnapshot
from harness.core.ports import ArtifactStore


class WorkspaceService:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def archive(
        self, *, tenant_id: str, session_id: str, workspace: Path
    ) -> WorkspaceSnapshot:
        snapshot_id = f"snapshot_{uuid4().hex}"

        def pack() -> bytes:
            buffer = BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                for path in sorted(workspace.rglob("*")):
                    archive.add(path, arcname=path.relative_to(workspace))
            return buffer.getvalue()

        content = await asyncio.to_thread(pack)
        stored = await self._store.put(tenant_id, snapshot_id, content)
        return WorkspaceSnapshot(
            snapshot_id=snapshot_id,
            session_id=session_id,
            tenant_id=tenant_id,
            object_key=stored.object_key,
            sha256=stored.sha256,
            created_at=datetime.now(UTC),
        )

    async def restore(self, snapshot: WorkspaceSnapshot, *, workspace: Path) -> None:
        content = await self._store.get(snapshot.tenant_id, snapshot.snapshot_id)
        if hashlib.sha256(content).hexdigest() != snapshot.sha256:
            raise ValueError("workspace snapshot hash mismatch")

        def unpack() -> None:
            root = workspace.resolve()
            with tarfile.open(fileobj=BytesIO(content), mode="r:gz") as archive:
                for member in archive.getmembers():
                    target = (root / member.name).resolve()
                    if not target.is_relative_to(root):
                        raise ValueError("workspace archive contains an unsafe path")
                archive.extractall(root, filter="data")

        await asyncio.to_thread(unpack)
