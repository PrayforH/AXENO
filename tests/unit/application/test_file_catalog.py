from datetime import UTC, datetime

import pytest

from harness.adapters.memory import InMemoryThreadFileRepository
from harness.application.file_catalog import FileCatalogService
from harness.core.models import ExecutionIdentity, ThreadFileKind

NOW = datetime(2026, 7, 13, tzinfo=UTC)


@pytest.mark.asyncio
async def test_catalog_records_original_and_derived_lineage_with_thread_scope() -> None:
    sequence = 0

    def ids(prefix: str) -> str:
        nonlocal sequence
        sequence += 1
        return f"{prefix}-{sequence}"

    service = FileCatalogService(
        InMemoryThreadFileRepository(), clock=lambda: NOW, id_generator=ids
    )
    identity = ExecutionIdentity(
        tenant_id="tenant-a",
        user_id="alice",
        project_id="agent-a",
        session_id="session-a",
        run_id="run-a",
        agent_name="agent-a",
        agent_version="1.0.0",
    )

    original = await service.record_original(
        identity=identity,
        input_artifact_id="input-a",
        name="report.docx",
        media_type="application/docx",
        path="inputs/original/report.docx",
    )
    derived = await service.record_derived(
        identity=identity,
        parent=original,
        name="report.md",
        media_type="text/markdown",
        path="inputs/processed/report/report.md",
        metadata={"headings": ["Report"]},
    )

    assert original.kind is ThreadFileKind.ORIGINAL
    assert derived.kind is ThreadFileKind.DERIVED
    assert derived.parent_file_id == original.file_id
    assert await service.list_for_thread(identity) == [original, derived]
    other = identity.model_copy(update={"user_id": "bob"})
    assert await service.list_for_thread(other) == []

