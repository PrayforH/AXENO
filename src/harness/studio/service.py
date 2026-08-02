"""Agent Studio draft lifecycle and immutable publication orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from harness.auth.audit import AuditService
from harness.core.errors import ConflictError, NotFoundError
from harness.core.models import AgentVersion, AgentVersionStatus
from harness.core.ports import AgentRegistry
from harness.knowledge.service import KnowledgeService
from harness.studio.bundle_import import AgentBundleImportError, parse_agent_bundle
from harness.studio.catalog_service import CapabilityCatalogService
from harness.studio.compiler import (
    AgentDraftCompiler,
    CompiledAgentDraft,
    DraftCompilationError,
)
from harness.studio.factory import create_draft_spec
from harness.studio.models import (
    AgentDraft,
    AgentDraftSummary,
    CapabilityCatalog,
    CreateAgentDraftRequest,
    DraftValidationResult,
    ImportedAgentBundle,
    ReplaceAgentDraftRequest,
    ValidationIssue,
    ValidationSeverity,
)
from harness.studio.nexau_export import NexauAgentArchive, export_nexau_agent
from harness.studio.repositories import AgentDraftRepository


class AgentBundlePublisher(Protocol):
    async def publish_bundle(
        self, tenant_id: str, owner_user_id: str, content: bytes
    ) -> AgentVersion: ...


class StudioPublisherNotConfiguredError(RuntimeError):
    pass


class StudioPublicationConflictError(ConflictError):
    pass


class AgentStudioService:
    def __init__(
        self,
        repository: AgentDraftRepository,
        compiler: AgentDraftCompiler | None = None,
        catalog: CapabilityCatalog | None = None,
        *,
        catalogs: CapabilityCatalogService | None = None,
        publisher: AgentBundlePublisher | None = None,
        registry: AgentRegistry | None = None,
        knowledge: KnowledgeService | None = None,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._compiler = compiler
        self._catalog = catalog
        self._catalogs = catalogs
        self._publisher = publisher
        self._registry = registry
        self._knowledge = knowledge
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_generator = id_generator or (lambda: f"draft_{uuid4().hex}")

    async def capabilities(self, tenant_id: str) -> CapabilityCatalog:
        if self._catalogs is not None:
            return (await self._catalogs.get(tenant_id)).catalog
        if self._catalog is None:
            raise RuntimeError("Agent Studio capability catalog is not configured")
        return self._catalog

    async def _compiler_for(self, tenant_id: str) -> AgentDraftCompiler:
        if self._catalogs is not None:
            record = await self._catalogs.get(tenant_id)
            return AgentDraftCompiler(
                record.catalog,
                catalog_revision=record.revision,
            )
        if self._compiler is None:
            raise RuntimeError("Agent Studio compiler is not configured")
        return self._compiler

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

    async def get(self, tenant_id: str, owner_user_id: str, draft_id: str) -> AgentDraft:
        return await self._repository.get(tenant_id, owner_user_id, draft_id)

    async def list(self, tenant_id: str, owner_user_id: str) -> list[AgentDraftSummary]:
        return [
            AgentDraftSummary.from_draft(draft)
            for draft in await self._repository.list_for_user(tenant_id, owner_user_id)
        ]

    async def replace(
        self,
        *,
        tenant_id: str,
        user_id: str,
        draft_id: str,
        request: ReplaceAgentDraftRequest,
    ) -> AgentDraft:
        current = await self._repository.get(tenant_id, user_id, draft_id)
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
        self, tenant_id: str, owner_user_id: str, draft_id: str
    ) -> DraftValidationResult:
        compiler = await self._compiler_for(tenant_id)
        draft = await self.get(tenant_id, owner_user_id, draft_id)
        validation = compiler.validate(draft)
        dependency_issues = await self._dependency_issues(tenant_id, owner_user_id, draft)
        if not dependency_issues:
            return validation
        return validation.model_copy(
            update={
                "ready": False,
                "issues": (*validation.issues, *dependency_issues),
            }
        )

    async def bundle(self, tenant_id: str, owner_user_id: str, draft_id: str) -> CompiledAgentDraft:
        compiler = await self._compiler_for(tenant_id)
        return compiler.compile(await self.get(tenant_id, owner_user_id, draft_id))

    async def nexau_bundle(
        self, tenant_id: str, owner_user_id: str, draft_id: str
    ) -> NexauAgentArchive:
        catalog = await self.capabilities(tenant_id)
        return export_nexau_agent(
            await self.get(tenant_id, owner_user_id, draft_id),
            mcp_capabilities={item.reference: item for item in catalog.mcp_servers},
        )

    async def import_bundle(
        self,
        *,
        tenant_id: str,
        user_id: str,
        content: bytes,
    ) -> ImportedAgentBundle:
        parsed = parse_agent_bundle(content)
        now = self._clock()
        draft = AgentDraft(
            draftId=self._id_generator(),
            tenantId=tenant_id,
            revision=1,
            spec=parsed.spec,
            createdBy=user_id,
            updatedBy=user_id,
            createdAt=now,
            updatedAt=now,
        )
        compiler = await self._compiler_for(tenant_id)
        round_trip_verified = False
        try:
            compiled = compiler.compile(draft)
            round_trip_verified = compiled.report.package_hash == parsed.package_hash
        except DraftCompilationError:
            if parsed.lossless:
                raise
        if parsed.lossless and not round_trip_verified:
            raise AgentBundleImportError(
                "Studio Bundle 无法按当前编译器无损重建；请检查能力目录或 Bundle 版本"
            )
        await self._repository.add(draft)
        if self._audit is not None:
            await self._audit.record(
                tenant_id=tenant_id,
                user_id=user_id,
                action="studio.draft.import",
                resource_type="agent_draft",
                resource_id=draft.draft_id,
                outcome="success",
                details={
                    "agent_name": draft.spec.name,
                    "agent_version": draft.spec.version,
                    "source_content_hash": parsed.content_hash,
                    "source_package_hash": parsed.package_hash,
                    "lossless": parsed.lossless,
                    "round_trip_verified": round_trip_verified,
                },
            )
        return ImportedAgentBundle(
            draft=draft,
            sourceContentHash=parsed.content_hash,
            sourcePackageHash=parsed.package_hash,
            lossless=parsed.lossless,
            roundTripVerified=round_trip_verified,
            warnings=parsed.warnings,
        )

    async def publish(
        self,
        *,
        tenant_id: str,
        user_id: str,
        draft_id: str,
        expected_revision: int | None = None,
    ) -> AgentVersion:
        if self._publisher is None:
            raise StudioPublisherNotConfiguredError("Agent Studio publisher is not configured")
        draft = await self.get(tenant_id, user_id, draft_id)
        compiler = await self._compiler_for(tenant_id)
        try:
            if expected_revision is not None and draft.revision != expected_revision:
                raise ConflictError(
                    "Agent draft revision changed before publish: "
                    f"expected={expected_revision} actual={draft.revision}"
                )
            compiled = compiler.compile(draft)
            dependency_issues = await self._dependency_issues(tenant_id, user_id, draft)
            if dependency_issues:
                raise DraftCompilationError(dependency_issues)
            existing = await self._idempotent_version(tenant_id, user_id, draft, compiled)
            if existing is not None:
                await self._record_publish_audit(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    draft_id=draft_id,
                    draft_revision=draft.revision,
                    version=existing,
                    dependencies=tuple(sorted({item.ref for item in draft.spec.subagents})),
                    idempotent=True,
                )
                return existing
            try:
                version = await self._publisher.publish_bundle(tenant_id, user_id, compiled.bundle)
            except ConflictError as error:
                raise StudioPublicationConflictError(
                    f"Agent version content conflicts with existing immutable release: "
                    f"{draft.spec.name}@{draft.spec.version}"
                ) from error
        except Exception as error:
            await self._record_publish_failure(
                tenant_id=tenant_id,
                user_id=user_id,
                draft=draft,
                error=error,
            )
            raise
        published = draft.model_copy(
            update={
                "revision": draft.revision + 1,
                "updated_by": user_id,
                "updated_at": self._clock(),
                "published_version": version.version,
                "published_hash": version.manifest_hash,
                "published_package_hash": version.package_hash,
            }
        )
        try:
            await self._repository.replace(draft.revision, published)
        except Exception as error:
            await self._record_publish_failure(
                tenant_id=tenant_id,
                user_id=user_id,
                draft=draft,
                error=error,
            )
            raise
        await self._record_publish_audit(
            tenant_id=tenant_id,
            user_id=user_id,
            draft_id=draft_id,
            draft_revision=published.revision,
            version=version,
            dependencies=tuple(sorted({item.ref for item in draft.spec.subagents})),
            idempotent=False,
        )
        return version

    async def _dependency_issues(
        self, tenant_id: str, owner_user_id: str, draft: AgentDraft
    ) -> tuple[ValidationIssue, ...]:
        references = tuple(sorted({item.ref for item in draft.spec.subagents}))
        knowledge_references = tuple(sorted(set(draft.spec.knowledge_references)))
        issues: list[ValidationIssue] = []
        if knowledge_references:
            if self._knowledge is None:
                issues.append(
                    ValidationIssue(
                        code="knowledge_registry_unavailable",
                        message="无法复验知识库引用",
                        severity=ValidationSeverity.ERROR,
                        path="knowledgeReferences",
                    )
                )
            else:
                for reference in knowledge_references:
                    try:
                        await self._knowledge.get_base(tenant_id, reference)
                    except NotFoundError:
                        issues.append(
                            ValidationIssue(
                                code="knowledge_base_not_found",
                                message=f"知识库尚未注册：{reference}",
                                severity=ValidationSeverity.ERROR,
                                path="knowledgeReferences",
                            )
                        )
        if not references:
            return tuple(issues)
        if self._registry is None:
            issues.append(
                ValidationIssue(
                    code="subagent_registry_unavailable",
                    message="无法复验固定版本 Sub Agent",
                    severity=ValidationSeverity.ERROR,
                    path="subagents",
                )
            )
            return tuple(issues)
        tenant_drafts = await self._repository.list_for_user(tenant_id, owner_user_id)
        for reference in references:
            name, version_id = reference.rsplit("@", 1)
            try:
                version = await self._registry.get(tenant_id, owner_user_id, name, version_id)
            except NotFoundError:
                issues.append(
                    ValidationIssue(
                        code="subagent_not_published",
                        message=f"Sub Agent 尚未发布：{reference}",
                        severity=ValidationSeverity.ERROR,
                        path="subagents",
                    )
                )
                continue
            if version.status is not AgentVersionStatus.PUBLISHED:
                issues.append(
                    ValidationIssue(
                        code="subagent_not_published",
                        message=f"Sub Agent 不是已发布状态：{reference}",
                        severity=ValidationSeverity.ERROR,
                        path="subagents",
                    )
                )
                continue
            studio_source = next(
                (
                    item
                    for item in tenant_drafts
                    if item.spec.name == name and item.published_version == version_id
                ),
                None,
            )
            if studio_source is not None and (
                studio_source.published_hash != version.manifest_hash
                or studio_source.published_package_hash != version.package_hash
            ):
                issues.append(
                    ValidationIssue(
                        code="subagent_version_drift",
                        message=f"Sub Agent 发布哈希漂移：{reference}",
                        severity=ValidationSeverity.ERROR,
                        path="subagents",
                    )
                )
        return tuple(issues)

    async def _idempotent_version(
        self,
        tenant_id: str,
        owner_user_id: str,
        draft: AgentDraft,
        compiled: CompiledAgentDraft,
    ) -> AgentVersion | None:
        if (
            draft.published_version != draft.spec.version
            or draft.published_hash != compiled.report.snapshot.content_hash
            or draft.published_package_hash != compiled.report.package_hash
        ):
            return None
        if self._registry is None:
            raise StudioPublicationConflictError(
                "Published Draft cannot be verified against the Agent Registry"
            )
        try:
            existing = await self._registry.get(
                tenant_id, owner_user_id, draft.spec.name, draft.spec.version
            )
        except NotFoundError as error:
            raise StudioPublicationConflictError(
                "Draft publication metadata points to a missing Agent version"
            ) from error
        if (
            existing.status is not AgentVersionStatus.PUBLISHED
            or existing.manifest_hash != compiled.report.snapshot.content_hash
            or existing.package_hash != compiled.report.package_hash
        ):
            raise StudioPublicationConflictError(
                "Draft publication metadata differs from the immutable Agent version"
            )
        return existing

    async def _record_publish_audit(
        self,
        *,
        tenant_id: str,
        user_id: str,
        draft_id: str,
        draft_revision: int,
        version: AgentVersion,
        dependencies: tuple[str, ...],
        idempotent: bool,
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            tenant_id=tenant_id,
            user_id=user_id,
            action="studio.publish",
            resource_type="agent_draft",
            resource_id=draft_id,
            outcome="success",
            details={
                "name": version.name,
                "version": version.version,
                "manifest_hash": version.manifest_hash,
                "package_hash": version.package_hash or "",
                "draft_revision": draft_revision,
                "dependencies": list(dependencies),
                "idempotent": idempotent,
            },
        )

    async def _record_publish_failure(
        self,
        *,
        tenant_id: str,
        user_id: str,
        draft: AgentDraft,
        error: Exception,
    ) -> None:
        if self._audit is None:
            return
        if isinstance(error, DraftCompilationError):
            error_code = "draft_not_ready"
        elif isinstance(error, StudioPublicationConflictError):
            error_code = "version_conflict"
        elif isinstance(error, ConflictError):
            error_code = "draft_conflict"
        else:
            error_code = "publish_failed"
        try:
            await self._audit.record(
                tenant_id=tenant_id,
                user_id=user_id,
                action="studio.publish",
                resource_type="agent_draft",
                resource_id=draft.draft_id,
                outcome="denied",
                details={
                    "name": draft.spec.name,
                    "version": draft.spec.version,
                    "draft_revision": draft.revision,
                    "error_code": error_code,
                },
            )
        except Exception:
            # Preserve the authoritative publication failure. The request-level audit
            # middleware still records the denied HTTP result.
            pass
