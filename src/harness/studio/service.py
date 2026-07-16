"""Agent Studio draft lifecycle and immutable publication orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from harness.core.models import AgentVersion
from harness.studio.compiler import AgentDraftCompiler, CompiledAgentDraft
from harness.studio.factory import create_draft_spec
from harness.studio.models import (
    AgentDraft,
    AgentDraftSummary,
    CapabilityCatalog,
    CreateAgentDraftRequest,
    DraftValidationResult,
    ReplaceAgentDraftRequest,
)
from harness.studio.repositories import AgentDraftRepository


class AgentBundlePublisher(Protocol):
    async def publish_bundle(self, tenant_id: str, content: bytes) -> AgentVersion: ...


class StudioPublisherNotConfiguredError(RuntimeError):
    pass


class AgentStudioService:
    def __init__(
        self,
        repository: AgentDraftRepository,
        compiler: AgentDraftCompiler,
        catalog: CapabilityCatalog,
        *,
        publisher: AgentBundlePublisher | None = None,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._compiler = compiler
        self._catalog = catalog
        self._publisher = publisher
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_generator = id_generator or (lambda: f"draft_{uuid4().hex}")

    @property
    def catalog(self) -> CapabilityCatalog:
        return self._catalog

    async def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        request: CreateAgentDraftRequest,
    ) -> AgentDraft:
        now = self._clock()
        draft = AgentDraft(
            draftId=self._id_generator(),
            tenantId=tenant_id,
            revision=1,
            spec=create_draft_spec(
                name=request.name,
                domain=request.domain,
                display_name=request.display_name,
                description=request.description,
                template=request.template,
            ),
            createdBy=user_id,
            updatedBy=user_id,
            createdAt=now,
            updatedAt=now,
        )
        await self._repository.add(draft)
        return draft

    async def get(self, tenant_id: str, draft_id: str) -> AgentDraft:
        return await self._repository.get(tenant_id, draft_id)

    async def list(self, tenant_id: str) -> list[AgentDraftSummary]:
        return [
            AgentDraftSummary.from_draft(draft)
            for draft in await self._repository.list_for_tenant(tenant_id)
        ]

    async def replace(
        self,
        *,
        tenant_id: str,
        user_id: str,
        draft_id: str,
        request: ReplaceAgentDraftRequest,
    ) -> AgentDraft:
        current = await self._repository.get(tenant_id, draft_id)
        updated = current.model_copy(
            update={
                "revision": current.revision + 1,
                "spec": request.spec,
                "updated_by": user_id,
                "updated_at": self._clock(),
            }
        )
        await self._repository.replace(request.expected_revision, updated)
        return updated

    async def validate(
        self, tenant_id: str, draft_id: str
    ) -> DraftValidationResult:
        return self._compiler.validate(await self.get(tenant_id, draft_id))

    async def bundle(self, tenant_id: str, draft_id: str) -> CompiledAgentDraft:
        return self._compiler.compile(await self.get(tenant_id, draft_id))

    async def publish(
        self, *, tenant_id: str, user_id: str, draft_id: str
    ) -> AgentVersion:
        if self._publisher is None:
            raise StudioPublisherNotConfiguredError(
                "Agent Studio publisher is not configured"
            )
        draft = await self.get(tenant_id, draft_id)
        compiled = self._compiler.compile(draft)
        version = await self._publisher.publish_bundle(tenant_id, compiled.bundle)
        published = draft.model_copy(
            update={
                "revision": draft.revision + 1,
                "updated_by": user_id,
                "updated_at": self._clock(),
                "published_version": version.version,
                "published_hash": version.manifest_hash,
            }
        )
        await self._repository.replace(draft.revision, published)
        return version
