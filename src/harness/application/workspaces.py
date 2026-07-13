"""Portable archive and restore for session workspaces."""

import asyncio
import hashlib
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from gzip import BadGzipFile
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from harness.core.models import WorkspaceSnapshot
from harness.core.ports import ArtifactStore, WorkspaceSnapshotRepository


@dataclass(frozen=True)
class WorkspacePolicy:
    restore_session: bool = True
    archive_on_complete: bool = True


class WorkspacePolicyResolver(Protocol):
    async def __call__(
        self, tenant_id: str, agent_name: str, agent_version: str
    ) -> WorkspacePolicy: ...


class WorkspaceService:
    def __init__(
        self,
        store: ArtifactStore,
        *,
        snapshots: WorkspaceSnapshotRepository | None = None,
        max_archive_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        self._store = store
        self._snapshots = snapshots
        self._max_archive_bytes = max_archive_bytes

    async def archive(
        self, *, tenant_id: str, session_id: str, workspace: Path
    ) -> WorkspaceSnapshot:
        snapshot_id = f"snapshot_{uuid4().hex}"

        def pack() -> bytes:
            buffer = BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                for path in sorted(workspace.rglob("*")):
                    if path.is_symlink():
                        raise ValueError("workspace contains an unsafe symlink")
                    archive.add(
                        path,
                        arcname=path.relative_to(workspace),
                        recursive=False,
                    )
            return buffer.getvalue()

        content = await asyncio.to_thread(pack)
        stored = await self._store.put(tenant_id, snapshot_id, content)
        snapshot = WorkspaceSnapshot(
            snapshot_id=snapshot_id,
            session_id=session_id,
            tenant_id=tenant_id,
            object_key=stored.object_key,
            sha256=stored.sha256,
            created_at=datetime.now(UTC),
        )
        if self._snapshots is not None:
            await self._snapshots.add(snapshot)
        return snapshot

    async def restore_latest(
        self, *, tenant_id: str, session_id: str, workspace: Path
    ) -> WorkspaceSnapshot | None:
        if self._snapshots is None:
            return None
        snapshot = await self._snapshots.latest(tenant_id, session_id)
        if snapshot is None:
            return None
        await self.restore(snapshot, workspace=workspace)
        return snapshot

    async def restore(self, snapshot: WorkspaceSnapshot, *, workspace: Path) -> None:
        content = await self._store.get(snapshot.tenant_id, snapshot.snapshot_id)
        if hashlib.sha256(content).hexdigest() != snapshot.sha256:
            raise ValueError("workspace snapshot hash mismatch")

        def unpack() -> None:
            workspace.mkdir(parents=True, exist_ok=True)
            root = workspace.resolve()
            try:
                archive = tarfile.open(fileobj=BytesIO(content), mode="r:gz")
            except (tarfile.TarError, BadGzipFile, OSError, EOFError) as error:
                raise ValueError("invalid workspace archive") from error
            with archive:
                members = archive.getmembers()
                total_size = 0
                for member in archive.getmembers():
                    normalized_name = member.name.replace("\\", "/")
                    relative = Path(normalized_name)
                    target = (root / relative).resolve()
                    if (
                        relative.is_absolute()
                        or ".." in relative.parts
                        or not target.is_relative_to(root)
                        or member.issym()
                        or member.islnk()
                        or not (member.isdir() or member.isreg())
                    ):
                        raise ValueError("workspace archive contains an unsafe path")
                    total_size += member.size
                    if total_size > self._max_archive_bytes:
                        raise ValueError("workspace archive exceeds extraction limit")
                for member in members:
                    target = root / Path(member.name.replace("\\", "/"))
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("invalid workspace archive")
                    target.write_bytes(source.read())
                    target.chmod(member.mode & 0o755)

        await asyncio.to_thread(unpack)
