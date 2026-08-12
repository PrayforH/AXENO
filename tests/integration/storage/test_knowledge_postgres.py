from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from harness.knowledge.models import (
    CreateKnowledgeBaseRequest,
    CreateKnowledgeSourceRequest,
)
from harness.knowledge.service import KnowledgeService
from harness.storage.database import SessionFactory
from harness.storage.knowledge_repository import PostgresKnowledgeRepository

DatabaseFixture = tuple[AsyncEngine, SessionFactory]


@pytest.mark.asyncio
async def test_postgres_knowledge_snapshot_is_durable_and_tenant_scoped(
    database: DatabaseFixture,
) -> None:
    _, sessions = database
    first = KnowledgeService(PostgresKnowledgeRepository(sessions))
    source, sync = await first.create_source(
        "tenant-a",
        "owner-a",
        CreateKnowledgeSourceRequest.model_validate(
            {
                "reference": "handbook",
                "displayName": "Employee handbook",
                "kind": "file",
                "config": {
                    "type": "file",
                    "documents": [
                        {
                            "documentId": "leave",
                            "title": "Leave policy",
                            "content": "Employees receive fifteen days of annual leave.",
                        }
                    ],
                },
            }
        ),
    )
    await first.create_base(
        "tenant-a",
        "owner-a",
        CreateKnowledgeBaseRequest(
            reference="company-policy",
            displayName="Company policy",
            sourceReferences=("handbook",),
        ),
    )

    restarted = KnowledgeService(PostgresKnowledgeRepository(sessions))
    result = await restarted.search(
        "tenant-a",
        "owner-a",
        "annual leave",
        knowledge_base_references=("company-policy",),
    )

    assert sync is not None
    assert sync.status.value == "succeeded"
    assert result.hits[0].citation.snapshot_id == source.active_snapshot_id
    assert result.hits[0].citation.document_id == "leave"
    assert await restarted.list_bases("tenant-b") == ()
    assert await restarted.list_sources("tenant-b") == ()
