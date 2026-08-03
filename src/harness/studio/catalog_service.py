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


def _upgrade_system_managed_catalog(
    catalog: CapabilityCatalog,
) -> CapabilityCatalog | None:
    """Add new built-ins to a system-managed catalog without dropping tenant entries."""

    defaults = default_capability_catalog()
    route_ids = {route.route_id for route in catalog.model_routes}
    routes = list(catalog.model_routes)
    changed = False
    if not {"deepseek-v4-flash", "deepseek-v4-pro"} & route_ids:
        legacy = next(
            (route for route in routes if route.route_id == "new-api-default"),
            None,
        )
        if legacy is not None and set(legacy.models) == {
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        }:
            compatibility_route = legacy.model_copy(
                update={
                    "label": "DeepSeek V4（兼容路由）",
                    "models": ("deepseek-v4-pro",),
                    "version": legacy.version + 1,
                    "enabled": False,
                }
            )
            split_routes = (
                ModelRouteCapability(
                    routeId="deepseek-v4-flash",
                    label="DeepSeek V4 Flash",
                    provider=legacy.provider,
                    models=("deepseek-v4-flash",),
                    capabilities=legacy.capabilities,
                    credentialManaged=legacy.credential_managed,
                    credentialReference=legacy.credential_reference,
                ),
                ModelRouteCapability(
                    routeId="deepseek-v4-pro",
                    label="DeepSeek V4 Pro",
                    provider=legacy.provider,
                    models=("deepseek-v4-pro",),
                    capabilities=legacy.capabilities,
                    credentialManaged=legacy.credential_managed,
                    credentialReference=legacy.credential_reference,
                ),
            )
            migrated: list[ModelRouteCapability] = []
            for route in routes:
                migrated.append(compatibility_route if route is legacy else route)
                if route is legacy:
                    migrated.extend(split_routes)
            routes = migrated
            route_ids.update({"deepseek-v4-flash", "deepseek-v4-pro"})
            changed = True

    if "glm-5-2" not in route_ids:
        glm = next(route for route in defaults.model_routes if route.route_id == "glm-5-2")
        routes.append(glm)
        changed = True

    def append_missing(current: tuple, builtins: tuple, identifier: str) -> tuple:
        nonlocal changed
        identifiers = {getattr(item, identifier) for item in current}
        additions = tuple(item for item in builtins if getattr(item, identifier) not in identifiers)
        if additions:
            changed = True
        return (*current, *additions)

    upgraded = catalog.model_copy(
        update={
            "model_routes": append_missing(
                tuple(routes),
                defaults.model_routes,
                "route_id",
            ),
            "mcp_servers": append_missing(
                catalog.mcp_servers,
                defaults.mcp_servers,
                "reference",
            ),
            "policies": append_missing(
                catalog.policies,
                defaults.policies,
                "policy_id",
            ),
            "execution_profiles": append_missing(
                catalog.execution_profiles,
                defaults.execution_profiles,
                "profile_id",
            ),
        }
    )
    return upgraded if changed else None


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
        current = await self._repository.seed(seed)
        if current.updated_by == "system" or current.updated_by.startswith("system-"):
            upgraded_catalog = _upgrade_system_managed_catalog(current.catalog)
            updated_by = "system-route-migration"
        else:
            upgraded_catalog = None
            updated_by = current.updated_by
        catalog_for_scope = upgraded_catalog or current.catalog
        scoped_catalog = await self._scope_legacy_mcp_capabilities(
            tenant_id,
            catalog_for_scope,
        )
        if scoped_catalog is not None:
            upgraded_catalog = scoped_catalog
            updated_by = "system-user-resource-scope-migration"
        if upgraded_catalog is None or current.catalog == upgraded_catalog:
            return current
        upgraded = CapabilityCatalogRecord(
            tenantId=tenant_id,
            revision=current.revision + 1,
            catalog=upgraded_catalog,
            updatedBy=updated_by,
            updatedAt=self._clock(),
        )
        try:
            await self._repository.replace(current.revision, upgraded)
            return upgraded
        except ConflictError:
            # A tenant admin may have replaced the catalog after our read. Never
            # overwrite that concurrent decision with built-in defaults.
            return await self._repository.get(tenant_id)

    async def get_for_user(
        self,
        tenant_id: str,
        user_id: str,
    ) -> CapabilityCatalogRecord:
        """Return platform capabilities plus the current user's personal MCP overlay."""

        return self._record_for_user(await self.get(tenant_id), user_id)

    async def _scope_legacy_mcp_capabilities(
        self,
        tenant_id: str,
        catalog: CapabilityCatalog,
    ) -> CapabilityCatalog | None:
        platform_references = {item.reference for item in default_capability_catalog().mcp_servers}
        legacy = tuple(
            item
            for item in catalog.mcp_servers
            if item.owner_user_id is None and item.reference not in platform_references
        )
        if not legacy:
            return None
        owners_by_reference: dict[str, set[str]] = {}
        for draft in await self._drafts.list_all_for_tenant(tenant_id):
            for reference in draft.spec.mcp_servers:
                owners_by_reference.setdefault(reference, set()).add(draft.created_by)
        scoped: list[McpCapability] = []
        for capability in catalog.mcp_servers:
            if capability not in legacy:
                scoped.append(capability)
                continue
            owners = sorted(owners_by_reference.get(capability.reference, ()))
            if not owners:
                owners = ["legacy-unassigned"]
            allowed_profile_ids = tuple(
                profile.profile_id
                for profile in catalog.execution_profiles
                if capability.reference in profile.allowed_mcp_references
            )
            scoped.extend(
                capability.model_copy(
                    update={
                        "owner_user_id": owner,
                        "allowed_execution_profile_ids": allowed_profile_ids,
                    }
                )
                for owner in owners
            )
        return catalog.model_copy(update={"mcp_servers": tuple(scoped)})

    @staticmethod
    def _record_for_user(
        record: CapabilityCatalogRecord,
        user_id: str,
    ) -> CapabilityCatalogRecord:
        visible = tuple(
            item
            for item in record.catalog.mcp_servers
            if item.owner_user_id is None or item.owner_user_id == user_id
        )
        personal_references = {
            item.reference for item in record.catalog.mcp_servers if item.owner_user_id is not None
        }
        personal_by_profile: dict[str, list[str]] = {}
        for item in visible:
            if item.owner_user_id != user_id:
                continue
            for profile_id in item.allowed_execution_profile_ids:
                personal_by_profile.setdefault(profile_id, []).append(item.reference)
        execution_profiles = tuple(
            profile.model_copy(
                update={
                    "allowed_mcp_references": tuple(
                        dict.fromkeys(
                            (
                                *(
                                    reference
                                    for reference in profile.allowed_mcp_references
                                    if reference not in personal_references
                                ),
                                *personal_by_profile.get(profile.profile_id, ()),
                            )
                        )
                    )
                }
            )
            for profile in record.catalog.execution_profiles
        )
        return record.model_copy(
            update={
                "updated_by": "personal-catalog",
                "catalog": record.catalog.model_copy(
                    update={
                        "mcp_servers": visible,
                        "execution_profiles": execution_profiles,
                    }
                )
            }
        )

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
        user_id: str,
        resource_type: CatalogResourceType,
        resource_id: str,
    ) -> CatalogImpact:
        catalog = (await self.get_for_user(tenant_id, user_id)).catalog
        if not self._contains(catalog, resource_type, resource_id):
            raise NotFoundError(f"Catalog resource not found: {resource_type}/{resource_id}")
        affected: list[str] = []
        drafts = (
            await self._drafts.list_for_user(tenant_id, user_id)
            if resource_type == "mcp"
            else await self._drafts.list_all_for_tenant(tenant_id)
        )
        for draft in drafts:
            spec = draft.spec
            referenced = (resource_type == "modelRoute" and spec.model.route_id == resource_id) or (
                resource_type == "mcp" and resource_id in spec.mcp_servers
            )
            referenced = referenced or (
                resource_type == "policy" and spec.permission_policy == resource_id
            )
            referenced = referenced or (
                resource_type == "executionProfile" and spec.execution_profile == resource_id
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
        if resource_type == "mcp":
            own_entry = next(
                (
                    item
                    for item in current.catalog.mcp_servers
                    if item.reference == resource_id
                    and item.owner_user_id == user_id
                ),
                None,
            )
            if own_entry is None:
                if any(
                    item.reference == resource_id and item.owner_user_id is None
                    for item in current.catalog.mcp_servers
                ):
                    raise ConflictError(
                        "Platform MCP capabilities cannot be disabled"
                    )
                raise NotFoundError(f"Catalog resource not found: mcp/{resource_id}")
        impact = await self.impact(tenant_id, user_id, resource_type, resource_id)
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
            entry.model_copy(update={"enabled": False, "version": entry.version + 1})
            if getattr(entry, identifier) == resource_id
            and (resource_type != "mcp" or entry.owner_user_id == user_id)
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
        return CatalogMutationResult(
            record=self._record_for_user(record, user_id),
            impact=impact,
        )

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
            resource_type == "modelRoute" and isinstance(request.resource, ModelRouteCapability)
        ) or (resource_type == "mcp" and isinstance(request.resource, McpCapability))
        type_matches = type_matches or (
            resource_type == "policy" and isinstance(request.resource, PolicyCapability)
        )
        type_matches = type_matches or (
            resource_type == "executionProfile"
            and isinstance(request.resource, ExecutionProfileMetadata)
        )
        if not type_matches:
            raise ConflictError(f"Catalog resource type mismatch: expected {resource_type}")
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
        if resource_type == "mcp":
            platform_entry = next(
                (
                    entry
                    for entry in entries
                    if entry.reference == resource_id and entry.owner_user_id is None
                ),
                None,
            )
            if platform_entry is not None:
                raise ConflictError("Platform MCP capabilities cannot be overwritten")
            existing = next(
                (
                    entry
                    for entry in entries
                    if entry.reference == resource_id and entry.owner_user_id == user_id
                ),
                None,
            )
        else:
            existing = next(
                (entry for entry in entries if getattr(entry, identifier) == resource_id),
                None,
            )
        impact = (
            await self.impact(tenant_id, user_id, resource_type, resource_id)
            if existing is not None
            else CatalogImpact(
                resourceType=resource_type,
                resourceId=resource_id,
                draftIds=(),
            )
        )
        resource_updates: dict[str, object] = {
            "version": 1 if existing is None else existing.version + 1
        }
        if resource_type == "mcp":
            resource_updates["owner_user_id"] = user_id
        if resource_type == "mcp" and request.allowed_execution_profile_ids is not None:
            selected_profile_ids = set(request.allowed_execution_profile_ids)
            profiles_by_id = {
                profile.profile_id: profile for profile in current.catalog.execution_profiles
            }
            unknown_profile_ids = selected_profile_ids.difference(profiles_by_id)
            if unknown_profile_ids:
                raise ConflictError(
                    "Unknown Execution Profiles: " + ", ".join(sorted(unknown_profile_ids))
                )
            unavailable_profile_ids = {
                profile_id
                for profile_id in selected_profile_ids
                if not profiles_by_id[profile_id].enabled
            }
            if unavailable_profile_ids:
                raise ConflictError(
                    "Disabled Execution Profiles cannot be authorized: "
                    + ", ".join(sorted(unavailable_profile_ids))
                )
            incompatible_profile_ids = {
                profile_id
                for profile_id in selected_profile_ids
                if request.resource.network_access not in profiles_by_id[profile_id].network_access
            }
            if incompatible_profile_ids:
                raise ConflictError(
                    f"MCP network access {request.resource.network_access.value} "
                    "is not supported by "
                    "Execution Profiles: " + ", ".join(sorted(incompatible_profile_ids))
                )
            resource_updates["allowed_execution_profile_ids"] = tuple(
                request.allowed_execution_profile_ids
            )
        elif resource_type == "mcp" and isinstance(existing, McpCapability):
            resource_updates["allowed_execution_profile_ids"] = (
                existing.allowed_execution_profile_ids
            )
        resource = request.resource.model_copy(update=resource_updates)
        updated_entries = tuple(
            resource
            if getattr(entry, identifier) == resource_id
            and (resource_type != "mcp" or entry.owner_user_id == user_id)
            else entry
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
        return CatalogMutationResult(
            record=self._record_for_user(record, user_id),
            impact=impact,
        )

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
            "executionProfile": {item.profile_id for item in catalog.execution_profiles},
        }
        return resource_id in identifiers[resource_type]
