from datetime import UTC, datetime, timedelta

import pytest

from harness.adapters.memory import InMemoryAgentRegistry
from harness.application.agents import AgentService
from harness.core.errors import ConflictError, NotFoundError
from harness.studio.catalog import default_capability_catalog
from harness.studio.compiler import AgentDraftCompiler
from harness.studio.models import (
    AgentTemplate,
    CreateAgentDraftRequest,
    ReplaceAgentDraftRequest,
)
from harness.studio.repositories import InMemoryAgentDraftRepository
from harness.studio.service import AgentStudioService

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def create_request() -> CreateAgentDraftRequest:
    return CreateAgentDraftRequest(
        name="contract-reviewer",
        domain="contract-review",
        displayName="合同审查助手",
        description="检查上传合同并生成有出处的风险清单。",
        template=AgentTemplate.ANALYST,
    )


def studio(*, publisher: AgentService | None = None) -> AgentStudioService:
    catalog = default_capability_catalog()
    return AgentStudioService(
        InMemoryAgentDraftRepository(),
        AgentDraftCompiler(catalog),
        catalog,
        publisher=publisher,
        clock=lambda: NOW,
        id_generator=lambda: "draft_contract",
    )


@pytest.mark.asyncio
async def test_drafts_are_tenant_scoped_and_return_summary_order() -> None:
    service = studio()
    created = await service.create(
        tenant_id="tenant-a", user_id="builder", request=create_request()
    )

    assert (await service.list("tenant-a"))[0].draft_id == created.draft_id
    assert await service.list("tenant-b") == []
    with pytest.raises(NotFoundError):
        await service.get("tenant-b", created.draft_id)


@pytest.mark.asyncio
async def test_replace_uses_optimistic_revision_and_preserves_publication_identity() -> None:
    service = studio()
    created = await service.create(
        tenant_id="tenant-a", user_id="builder", request=create_request()
    )
    changed_spec = created.spec.model_copy(
        update={"description": "更新后的合同审查说明。"}
    )
    request = ReplaceAgentDraftRequest(expectedRevision=1, spec=changed_spec)

    updated = await service.replace(
        tenant_id="tenant-a",
        user_id="builder-2",
        draft_id=created.draft_id,
        request=request,
    )

    assert updated.revision == 2
    assert updated.updated_by == "builder-2"
    with pytest.raises(ConflictError, match="revision changed"):
        await service.replace(
            tenant_id="tenant-a",
            user_id="stale-builder",
            draft_id=created.draft_id,
            request=request,
        )


@pytest.mark.asyncio
async def test_publish_reuses_production_bundle_gate_and_marks_draft() -> None:
    registry = InMemoryAgentRegistry()
    publisher = AgentService(
        registry,
        clock=lambda: NOW + timedelta(seconds=1),
        environment="production",
    )
    service = studio(publisher=publisher)
    created = await service.create(
        tenant_id="tenant-a", user_id="builder", request=create_request()
    )

    version = await service.publish(
        tenant_id="tenant-a", user_id="publisher", draft_id=created.draft_id
    )
    stored = await service.get("tenant-a", created.draft_id)

    assert version.name == "contract-reviewer"
    assert version.version == "0.1.0"
    assert version.package_hash is not None
    assert stored.published_version == "0.1.0"
    assert stored.published_hash == version.manifest_hash
    assert stored.updated_by == "publisher"
    assert stored.revision == 2
