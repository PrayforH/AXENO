"""Catalog seeding, optimistic updates and Draft impact analysis."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from harness.core.errors import ConflictError, NotFoundError
from harness.studio.catalog import default_capability_catalog
from harness.studio.catalog_repository import CapabilityCatalogRepository
from harness.studio.models import (
    CapabilityCatalog,
    CapabilityCatalogRecord,
    CatalogImpact,
    CatalogMutationResult,
    ExecutionProfileMetadata,
    McpCapability,
    ModelRouteCapability,
    PolicyCapability,
    ReplaceCapabilityCatalogRequest,
    UpsertCatalogResourceRequest,
)
from harness.studio.repositories import AgentDraftRepository

CatalogResourceType = Literal["modelRoute", "mcp", "policy", "executionProfile"]


class CapabilityCatalogService:
    def __init__(
        self,
        repository: CapabilityCatalogRepository,
        drafts: AgentDraftRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._drafts = drafts
        self._clock = clock or (lambda: datetime.now(UTC))

    async def get(self, tenant_id: str) -> CapabilityCatalogRecord:
        seed = CapabilityCatalogRecord(
            tenantId=tenant_id,
            revision=1,
            catalog=default_capability_catalog(),
            updatedBy="system",
            updatedAt=self._clock(),
        )
        return await self._repository.seed(seed)

    async def replace(
        self,
        *,
        tenant_id: str,
        user_id: str,
        request: ReplaceCapabilityCatalogRequest,
    ) -> CapabilityCatalogRecord:
        current = await self.get(tenant_id)
        updated = CapabilityCatalogRecord(
            tenantId=tenant_id,
            revision=current.revision + 1,
            catalog=request.catalog,
            updatedBy=user_id,
            updatedAt=self._clock(),
        )
        await self._repository.replace(request.expected_revision, updated)
        return updated

    async def impact(
        self,
        tenant_id: str,
        resource_type: CatalogResourceType,
        resource_id: str,
    ) -> CatalogImpact:
        catalog = (await self.get(tenant_id)).catalog
        if not self._contains(catalog, resource_type, resource_id):
            raise NotFoundError(
                f"Catalog resource not found: {resource_type}/{resource_id}"
            )
        affected: list[str] = []
        for draft in await self._drafts.list_for_tenant(tenant_id):
            spec = draft.spec
            referenced = (
                resource_type == "modelRoute" and spec.model.route_id == resource_id
            ) or (resource_type == "mcp" and resource_id in spec.mcp_servers)
            referenced = referenced or (
                resource_type == "policy" and spec.permission_policy == resource_id
            )
            referenced = referenced or (
                resource_type == "executionProfile"
                and spec.execution_profile == resource_id
            )
            if referenced:
                affected.append(draft.draft_id)
        return CatalogImpact(
            resourceType=resource_type,
            resourceId=resource_id,
            draftIds=tuple(sorted(affected)),
        )

    async def disable(
        self,
        *,
        tenant_id: str,
        user_id: str,
        resource_type: CatalogResourceType,
        resource_id: str,
        expected_revision: int,
    ) -> CatalogMutationResult:
        current = await self.get(tenant_id)
        impact = await self.impact(tenant_id, resource_type, resource_id)
        field = {
            "modelRoute": "model_routes",
            "mcp": "mcp_servers",
            "policy": "policies",
            "executionProfile": "execution_profiles",
        }[resource_type]
        identifier = {
            "modelRoute": "route_id",
            "mcp": "reference",
            "policy": "policy_id",
            "executionProfile": "profile_id",
        }[resource_type]
        entries = getattr(current.catalog, field)
        updated_entries = tuple(
            entry.model_copy(
                update={"enabled": False, "version": entry.version + 1}
            )
            if getattr(entry, identifier) == resource_id
            else entry
            for entry in entries
        )
        updated_catalog = current.catalog.model_copy(update={field: updated_entries})
        record = await self.replace(
            tenant_id=tenant_id,
            user_id=user_id,
            request=ReplaceCapabilityCatalogRequest(
                expectedRevision=expected_revision,
                catalog=updated_catalog,
            ),
        )
        return CatalogMutationResult(record=record, impact=impact)

    async def upsert(
        self,
        *,
        tenant_id: str,
        user_id: str,
        resource_type: CatalogResourceType,
        resource_id: str,
        request: UpsertCatalogResourceRequest,
    ) -> CatalogMutationResult:
        type_matches = (
            resource_type == "modelRoute"
            and isinstance(request.resource, ModelRouteCapability)
        ) or (resource_type == "mcp" and isinstance(request.resource, McpCapability))
        type_matches = type_matches or (
            resource_type == "policy"
            and isinstance(request.resource, PolicyCapability)
        )
        type_matches = type_matches or (
            resource_type == "executionProfile"
            and isinstance(request.resource, ExecutionProfileMetadata)
        )
        if not type_matches:
            raise ConflictError(
                f"Catalog resource type mismatch: expected {resource_type}"
            )
        field = {
            "modelRoute": "model_routes",
            "mcp": "mcp_servers",
            "policy": "policies",
            "executionProfile": "execution_profiles",
        }[resource_type]
        identifier = {
            "modelRoute": "route_id",
            "mcp": "reference",
            "policy": "policy_id",
            "executionProfile": "profile_id",
        }[resource_type]
        if getattr(request.resource, identifier) != resource_id:
            raise ConflictError("Catalog resource path and body IDs must match")
        current = await self.get(tenant_id)
        entries = getattr(current.catalog, field)
        existing = next(
            (entry for entry in entries if getattr(entry, identifier) == resource_id),
            None,
        )
        impact = (
            await self.impact(tenant_id, resource_type, resource_id)
            if existing is not None
            else CatalogImpact(
                resourceType=resource_type,
                resourceId=resource_id,
                draftIds=(),
            )
        )
        resource = request.resource.model_copy(
            update={"version": 1 if existing is None else existing.version + 1}
        )
        updated_entries = tuple(
            resource if getattr(entry, identifier) == resource_id else entry
            for entry in entries
        )
        if existing is None:
            updated_entries = (*updated_entries, resource)
        catalog = current.catalog.model_copy(update={field: updated_entries})
        record = await self.replace(
            tenant_id=tenant_id,
            user_id=user_id,
            request=ReplaceCapabilityCatalogRequest(
                expectedRevision=request.expected_revision,
                catalog=catalog,
            ),
        )
        return CatalogMutationResult(record=record, impact=impact)

    @staticmethod
    def _contains(
        catalog: CapabilityCatalog,
        resource_type: CatalogResourceType,
        resource_id: str,
    ) -> bool:
        identifiers = {
            "modelRoute": {item.route_id for item in catalog.model_routes},
            "mcp": {item.reference for item in catalog.mcp_servers},
            "policy": {item.policy_id for item in catalog.policies},
            "executionProfile": {
                item.profile_id for item in catalog.execution_profiles
            },
        }
        return resource_id in identifiers[resource_type]
