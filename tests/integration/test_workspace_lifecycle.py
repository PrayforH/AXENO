from pathlib import Path

import pytest

from harness.adapters.memory import InMemoryArtifactStore
from harness.application.workspaces import WorkspaceService


@pytest.mark.asyncio
async def test_workspace_archive_and_restore_round_trip(tmp_path: Path) -> None:
    store = InMemoryArtifactStore()
    service = WorkspaceService(store)
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("input")
    (source / "nested").mkdir()
    (source / "nested" / "result.txt").write_text("result")

    snapshot = await service.archive(tenant_id="tenant-a", session_id="session-1", workspace=source)
    target = tmp_path / "target"
    target.mkdir()
    await service.restore(snapshot, workspace=target)

    assert (target / "input.txt").read_text() == "input"
    assert (target / "nested" / "result.txt").read_text() == "result"
