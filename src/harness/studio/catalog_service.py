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
    TemplateCapability,
    UpsertCatalogResourceRequest,
)
from harness.studio.repositories import AgentDraftRepository

CatalogResourceType = Literal["modelRoute", "mcp", "policy", "executionProfile"]
_RETIRED_PLATFORM_MODEL_ROUTES = frozenset({"anthropic-official"})
_EDITABLE_PLATFORM_MCP_REFERENCES = frozenset({"tavily-readonly"})


def _mcp_is_mutable_by(item: McpCapability, user_id: str) -> bool:
    return item.owner_user_id == user_id or (
        item.owner_user_id is None
        and item.reference in _EDITABLE_PLATFORM_MCP_REFERENCES
    )


def _retire_platform_model_routes(
    catalog: CapabilityCatalog,
) -> CapabilityCatalog | None:
    routes = tuple(
        route
        for route in catalog.model_routes
        if route.route_id not in _RETIRED_PLATFORM_MODEL_ROUTES
    )
    if len(routes) == len(catalog.model_routes):
        return None
    return catalog.model_copy(update={"model_routes": routes})


def _append_missing[
    CatalogEntry: (
        ModelRouteCapability,
        McpCapability,
        PolicyCapability,
        ExecutionProfileMetadata,
        TemplateCapability,
    )
](
    current: tuple[CatalogEntry, ...],
    builtins: tuple[CatalogEntry, ...],
    identifier: Callable[[CatalogEntry], str],
) -> tuple[tuple[CatalogEntry, ...], bool]:
    identifiers = {identifier(item) for item in current}
    additions = tuple(item for item in builtins if identifier(item) not in identifiers)
    return (*current, *additions), bool(additions)


def _upgrade_known_legacy_permission_copy(
    catalog: CapabilityCatalog,
) -> CapabilityCatalog | None:
    """Refresh exact historical defaults without touching tenant-authored copy."""

    defaults = default_capability_catalog()
    default_policies = {item.policy_id: item for item in defaults.policies}
    policies: list[PolicyCapability] = []
    changed = False
    for policy in catalog.policies:
        replacement = default_policies.get(policy.policy_id)
        if (
            replacement is not None
            and policy.policy_id == "production-standard"
            and policy.description == "允许受控文件写入，命令和高风险动作进入审批。"
        ):
            policies.append(
                policy.model_copy(
                    update={
                        "description": replacement.description,
                        "version": policy.version + 1,
                    }
                )
            )
            changed = True
        else:
            policies.append(policy)

    default_templates = {item.template: item for item in defaults.templates}
    templates: list[TemplateCapability] = []
    for template in catalog.templates:
        replacement = default_templates.get(template.template)
        if (
            replacement is not None
            and template.description == "在隔离工作区中生成或修改文件，高风险操作需审批。"
        ):
            templates.append(
                template.model_copy(update={"description": replacement.description})
            )
            changed = True
        else:
            templates.append(template)

    if not changed:
        return None
    return catalog.model_copy(
        update={"policies": tuple(policies), "templates": tuple(templates)}
    )


def _upgrade_system_managed_catalog(
    catalog: CapabilityCatalog,
) -> CapabilityCatalog | None:
    """Upgrade known system defaults without dropping tenant-authored entries."""

    defaults = default_capability_catalog()
    route_ids = {route.route_id for route in catalog.model_routes}
    routes = [
        route
        for route in catalog.model_routes
        if route.route_id not in _RETIRED_PLATFORM_MODEL_ROUTES
    ]
    changed = len(routes) != len(catalog.model_routes)
    normalized_routes = []
    for route in routes:
        if "vision" in route.capabilities and route.model_type == "chat":
            normalized_routes.append(route.model_copy(update={"model_type": "vision"}))
            changed = True
        else:
            normalized_routes.append(route)
    routes = normalized_routes
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

    routes, routes_changed = _append_missing(
        tuple(routes), defaults.model_routes, lambda item: item.route_id
    )
    mcp_servers, mcp_changed = _append_missing(
        catalog.mcp_servers, defaults.mcp_servers, lambda item: item.reference
    )
    policies, policies_changed = _append_missing(
        catalog.policies, defaults.policies, lambda item: item.policy_id
    )
    execution_profiles, profiles_changed = _append_missing(
        catalog.execution_profiles,
        defaults.execution_profiles,
        lambda item: item.profile_id,
    )
    templates, templates_changed = _append_missing(
        catalog.templates,
        defaults.templates,
        lambda item: item.template.value,
    )
    changed = changed or any(
        (
            routes_changed,
            mcp_changed,
            policies_changed,
            profiles_changed,
            templates_changed,
        )
    )

    upgraded = catalog.model_copy(
        update={
            "model_routes": routes,
            "mcp_servers": mcp_servers,
            "policies": policies,
            "execution_profiles": execution_profiles,
            "templates": templates,
        }
    )
    permission_copy_upgrade = _upgrade_known_legacy_permission_copy(upgraded)
    return permission_copy_upgrade or (upgraded if changed else None)


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
        retired_catalog = _retire_platform_model_routes(current.catalog)
        catalog_for_upgrade = retired_catalog or current.catalog
        if current.updated_by == "system" or current.updated_by.startswith("system-"):
            upgraded_catalog = (
                _upgrade_system_managed_catalog(catalog_for_upgrade)
                or retired_catalog
            )
            updated_by = "system-route-migration"
        else:
            upgraded_catalog = (
                _upgrade_known_legacy_permission_copy(catalog_for_upgrade)
                or retired_catalog
            )
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
        """Return platform controls plus only the current user's personal MCP entries."""

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
        visible_model_routes = tuple(
            # Endpoint details remain visible only through the administrator
            # model-management API. Runtime users select logical route IDs.
            item.model_copy(update={"base_url": None})
            for item in record.catalog.model_routes
        )
        personal = tuple(
            item for item in record.catalog.mcp_servers if item.owner_user_id == user_id
        )
        personal_overrides = {item.reference for item in personal}
        platform = tuple(
            item
            for item in record.catalog.mcp_servers
            if item.owner_user_id is None and item.reference not in personal_overrides
        )
        visible = (*platform, *personal)
        personal_references = {
            item.reference for item in record.catalog.mcp_servers if item.owner_user_id is not None
        }
        platform_mcp_references = {
            item.reference for item in record.catalog.mcp_servers if item.owner_user_id is None
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
                                    if (
                                        reference in platform_mcp_references
                                        and reference not in personal_overrides
                                    )
                                    or reference not in personal_references
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
                        "model_routes": visible_model_routes,
                        "mcp_servers": visible,
                        "execution_profiles": execution_profiles,
                    }
                ),
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
                    if item.reference == resource_id and _mcp_is_mutable_by(item, user_id)
                ),
                None,
            )
            if own_entry is None:
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
            and (resource_type != "mcp" or _mcp_is_mutable_by(entry, user_id))
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

    async def delete_mcp(
        self,
        *,
        tenant_id: str,
        user_id: str,
        resource_id: str,
        expected_revision: int,
    ) -> CatalogMutationResult:
        """Permanently remove an unreferenced user-managed MCP connection."""

        current = await self.get(tenant_id)
        own_entry = next(
            (
                item
                for item in current.catalog.mcp_servers
                if item.reference == resource_id and _mcp_is_mutable_by(item, user_id)
            ),
            None,
        )
        if own_entry is None:
            raise NotFoundError(f"Catalog resource not found: mcp/{resource_id}")
        impact = await self.impact(tenant_id, user_id, "mcp", resource_id)
        if impact.draft_ids:
            raise ConflictError(
                "Remove this capability from the affected agent drafts before deleting it: "
                + ", ".join(impact.draft_ids)
            )
        updated_catalog = current.catalog.model_copy(
            update={
                "mcp_servers": tuple(
                    item
                    for item in current.catalog.mcp_servers
                    if not (
                        item.reference == resource_id
                        and _mcp_is_mutable_by(item, user_id)
                    )
                )
            }
        )
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
            if not isinstance(request.resource, McpCapability):
                raise ConflictError("Catalog resource type does not match MCP payload")
            mcp_resource = request.resource
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
                if mcp_resource.network_access not in profiles_by_id[profile_id].network_access
            }
            if incompatible_profile_ids:
                raise ConflictError(
                    f"MCP network access {mcp_resource.network_access.value} "
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
