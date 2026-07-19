"""Immutable models used by the Agent Studio authoring control plane."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.core.manifest import ToolExposureMode
from harness.evals.suite import EvalCase


class StudioModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class AgentTemplate(StrEnum):
    ANALYST = "analyst"
    OPERATOR = "operator"
    ORCHESTRATOR = "orchestrator"


class CapabilityRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NetworkAccess(StrEnum):
    NONE = "none"
    INTERNAL = "internal"
    EXTERNAL = "external"


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class DraftModelSelection(StudioModel):
    route_id: str = Field(alias="routeId", min_length=1)
    model: str = Field(min_length=1)
    fallback_route_id: str | None = Field(default=None, alias="fallbackRouteId")
    fallback_model: str | None = Field(default=None, alias="fallbackModel")
    required_capabilities: tuple[str, ...] = Field(
        default=("streaming", "tool_use"), alias="requiredCapabilities"
    )


class DraftSkillFile(StudioModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=2 * 1024 * 1024)

    @model_validator(mode="after")
    def safe_relative_path(self) -> DraftSkillFile:
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or "\\" in self.path
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() == "SKILL.md"
        ):
            raise ValueError("Skill file path must be safe and cannot replace SKILL.md")
        return self


class DraftSkill(StudioModel):
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    description: str = Field(min_length=1, max_length=500)
    instructions: str = Field(min_length=1, max_length=512 * 1024)
    files: tuple[DraftSkillFile, ...] = ()

    @model_validator(mode="after")
    def unique_file_paths(self) -> DraftSkill:
        paths = [file.path for file in self.files]
        duplicates = sorted({path for path in paths if paths.count(path) > 1})
        if duplicates:
            raise ValueError(f"duplicate Skill file path: {', '.join(duplicates)}")
        return self


class DraftWorkspace(StudioModel):
    restore_session: bool = Field(default=True, alias="restoreSession")
    archive_on_complete: bool = Field(default=True, alias="archiveOnComplete")


class DraftLimits(StudioModel):
    max_turns: int = Field(default=15, alias="maxTurns", ge=1, le=200)
    timeout_seconds: int = Field(default=900, alias="timeoutSeconds", ge=1, le=86_400)
    max_budget_usd: float = Field(default=1, alias="maxBudgetUsd", gt=0)
    max_model_tokens: int = Field(default=200_000, alias="maxModelTokens", ge=1, le=10_000_000)
    max_subagents: int = Field(default=8, alias="maxSubagents", ge=1, le=32)
    max_subagent_tasks: int = Field(default=16, alias="maxSubagentTasks", ge=1, le=128)
    max_concurrent_subagents: int = Field(default=4, alias="maxConcurrentSubagents", ge=1, le=16)
    max_subagent_usage_units: int | None = Field(
        default=200_000, alias="maxSubagentUsageUnits", gt=0
    )


class DraftSubagent(StudioModel):
    alias: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    ref: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*@[^@]+$")
    responsibility: str = Field(min_length=1, max_length=500)
    background: bool = False


class AgentDraftSpec(StudioModel):
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    version: str = Field(default="0.1.0", min_length=1)
    display_name: str = Field(alias="displayName", min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    domain: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    template: AgentTemplate = AgentTemplate.ANALYST
    model: DraftModelSelection
    system_prompt: str = Field(alias="systemPrompt", min_length=1, max_length=512 * 1024)
    skills: tuple[DraftSkill, ...] = Field(min_length=1)
    builtin_tools: tuple[str, ...] = Field(default=(), alias="builtinTools")
    mcp_servers: tuple[str, ...] = Field(default=(), alias="mcpServers")
    tool_exposure_mode: ToolExposureMode = Field(
        default="eager",
        alias="toolExposureMode",
    )
    subagents: tuple[DraftSubagent, ...] = ()
    permission_policy: str = Field(alias="permissionPolicy", min_length=1)
    execution_profile: str = Field(
        default="isolated-default", alias="executionProfile", min_length=1
    )
    workspace: DraftWorkspace = DraftWorkspace()
    limits: DraftLimits = DraftLimits()
    evaluation_cases: tuple[EvalCase, ...] = Field(min_length=1, alias="evaluationCases")

    @model_validator(mode="after")
    def unique_capabilities(self) -> AgentDraftSpec:
        for label, values in (
            ("builtin tool", self.builtin_tools),
            ("MCP server", self.mcp_servers),
        ):
            duplicates = sorted({value for value in values if values.count(value) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label}: {', '.join(duplicates)}")
        aliases = [subagent.alias for subagent in self.subagents]
        duplicate_aliases = sorted({alias for alias in aliases if aliases.count(alias) > 1})
        if duplicate_aliases:
            raise ValueError(f"duplicate subagent alias: {', '.join(duplicate_aliases)}")
        skill_names = [skill.name for skill in self.skills]
        duplicate_skills = sorted({name for name in skill_names if skill_names.count(name) > 1})
        if duplicate_skills:
            raise ValueError(f"duplicate Skill: {', '.join(duplicate_skills)}")
        return self


class AgentDraft(StudioModel):
    draft_id: str = Field(alias="draftId", min_length=1)
    tenant_id: str = Field(alias="tenantId", min_length=1)
    revision: int = Field(ge=1)
    spec: AgentDraftSpec
    created_by: str = Field(alias="createdBy", min_length=1)
    updated_by: str = Field(alias="updatedBy", min_length=1)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    published_version: str | None = Field(default=None, alias="publishedVersion")
    published_hash: str | None = Field(
        default=None, alias="publishedHash", pattern=r"^[a-f0-9]{64}$"
    )
    published_package_hash: str | None = Field(
        default=None, alias="publishedPackageHash", pattern=r"^[a-f0-9]{64}$"
    )


class CreateAgentDraftRequest(StudioModel):
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    domain: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(alias="displayName", min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    template: AgentTemplate = AgentTemplate.ANALYST


class ReplaceAgentDraftRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    spec: AgentDraftSpec


class PublishAgentDraftRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)


class PublishedAgentVersion(StudioModel):
    tenant_id: str
    name: str
    version: str
    status: Literal["published"]
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    package_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime


class AgentDraftSummary(StudioModel):
    draft_id: str = Field(alias="draftId")
    name: str
    display_name: str = Field(alias="displayName")
    domain: str
    version: str
    template: AgentTemplate
    revision: int
    updated_at: datetime = Field(alias="updatedAt")
    published_version: str | None = Field(default=None, alias="publishedVersion")

    @classmethod
    def from_draft(cls, draft: AgentDraft) -> AgentDraftSummary:
        return cls(
            draftId=draft.draft_id,
            name=draft.spec.name,
            displayName=draft.spec.display_name,
            domain=draft.spec.domain,
            version=draft.spec.version,
            template=draft.spec.template,
            revision=draft.revision,
            updatedAt=draft.updated_at,
            publishedVersion=draft.published_version,
        )


class ModelRouteCapability(StudioModel):
    route_id: str = Field(alias="routeId")
    label: str
    provider: str
    models: tuple[str, ...]
    capabilities: tuple[str, ...]
    credential_managed: bool = Field(default=True, alias="credentialManaged")
    credential_reference: str | None = Field(
        default=None,
        alias="credentialReference",
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    version: int = Field(default=1, ge=1)
    enabled: bool = True


class BuiltinToolCapability(StudioModel):
    name: str
    label: str
    description: str
    risk: CapabilityRisk
    execution_location: str = Field(alias="executionLocation")
    approval_behavior: str = Field(alias="approvalBehavior")


class McpCapability(StudioModel):
    reference: str
    label: str
    description: str
    tools: tuple[str, ...]
    risk: CapabilityRisk
    network_access: NetworkAccess = Field(alias="networkAccess")
    sends_user_data: bool = Field(alias="sendsUserData")
    credential_managed: bool = Field(default=True, alias="credentialManaged")
    execution_location: str = Field(alias="executionLocation")
    preflight_required: bool = Field(default=True, alias="preflightRequired")
    credential_reference: str | None = Field(
        default=None,
        alias="credentialReference",
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    version: int = Field(default=1, ge=1)
    enabled: bool = True


class PolicyCapability(StudioModel):
    policy_id: str = Field(alias="policyId")
    label: str
    description: str
    risk: CapabilityRisk
    version: int = Field(default=1, ge=1)
    enabled: bool = True


class ExecutionProfileMetadata(StudioModel):
    profile_id: str = Field(alias="profileId", pattern=r"^[a-z][a-z0-9-]*$")
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=500)
    sandbox_provider: Literal["local", "daytona", "e2b", "gvisor"] = Field(alias="sandboxProvider")
    network_access: tuple[NetworkAccess, ...] = Field(alias="networkAccess")
    risk: CapabilityRisk
    cpu_millis: int = Field(default=1000, alias="cpuMillis", ge=100, le=16_000)
    memory_mib: int = Field(default=2048, alias="memoryMiB", ge=128, le=65_536)
    disk_mib: int = Field(default=10_240, alias="diskMiB", ge=512, le=1_048_576)
    ttl_seconds: int = Field(default=3600, alias="ttlSeconds", ge=60, le=86_400)
    network_policy_id: str = Field(
        default="deny-by-default",
        alias="networkPolicyId",
        pattern=r"^[a-z][a-z0-9-]*$",
    )
    allowed_mcp_references: tuple[str, ...] = Field(default=(), alias="allowedMcpReferences")
    provider_config_reference: str = Field(
        default="platform-default",
        alias="providerConfigReference",
        pattern=r"^[a-z][a-z0-9-]*$",
    )
    production_allowed: bool = Field(default=True, alias="productionAllowed")
    version: int = Field(default=1, ge=1)
    enabled: bool = True


class TemplateCapability(StudioModel):
    template: AgentTemplate
    label: str
    description: str


class CapabilityCatalog(StudioModel):
    model_routes: tuple[ModelRouteCapability, ...] = Field(alias="modelRoutes")
    builtin_tools: tuple[BuiltinToolCapability, ...] = Field(alias="builtinTools")
    mcp_servers: tuple[McpCapability, ...] = Field(alias="mcpServers")
    policies: tuple[PolicyCapability, ...]
    execution_profiles: tuple[ExecutionProfileMetadata, ...] = Field(
        default=(), alias="executionProfiles"
    )
    templates: tuple[TemplateCapability, ...]

    @model_validator(mode="after")
    def unique_managed_ids(self) -> CapabilityCatalog:
        collections = (
            ("model route", [item.route_id for item in self.model_routes]),
            ("MCP", [item.reference for item in self.mcp_servers]),
            ("policy", [item.policy_id for item in self.policies]),
            (
                "execution profile",
                [item.profile_id for item in self.execution_profiles],
            ),
        )
        for label, identifiers in collections:
            duplicates = sorted(
                {identifier for identifier in identifiers if identifiers.count(identifier) > 1}
            )
            if duplicates:
                raise ValueError(f"duplicate {label}: {', '.join(duplicates)}")
        return self


class CapabilityCatalogRecord(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    revision: int = Field(ge=1)
    catalog: CapabilityCatalog
    updated_by: str = Field(alias="updatedBy", min_length=1)
    updated_at: datetime = Field(alias="updatedAt")


class ReplaceCapabilityCatalogRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    catalog: CapabilityCatalog


class CatalogImpact(StudioModel):
    resource_type: Literal["modelRoute", "mcp", "policy", "executionProfile"] = Field(
        alias="resourceType"
    )
    resource_id: str = Field(alias="resourceId")
    draft_ids: tuple[str, ...] = Field(alias="draftIds")


class CatalogMutationResult(StudioModel):
    record: CapabilityCatalogRecord
    impact: CatalogImpact


CatalogManagedResource = (
    ModelRouteCapability | McpCapability | PolicyCapability | ExecutionProfileMetadata
)


class UpsertCatalogResourceRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    resource: CatalogManagedResource


class ValidationIssue(StudioModel):
    code: str
    message: str
    severity: ValidationSeverity
    path: str | None = None


class EffectiveAgentContract(StudioModel):
    model: str
    model_route: str = Field(alias="modelRoute")
    skills: int = Field(ge=0)
    builtin_tools: tuple[str, ...] = Field(alias="builtinTools")
    mcp_servers: tuple[str, ...] = Field(alias="mcpServers")
    tool_exposure_mode: ToolExposureMode = Field(alias="toolExposureMode")
    tool_directory_entries: int = Field(alias="toolDirectoryEntries", ge=0)
    network_access: NetworkAccess = Field(alias="networkAccess")
    network_summary: str = Field(alias="networkSummary")
    permission_policy: str = Field(alias="permissionPolicy")
    approval_summary: str = Field(alias="approvalSummary")
    sandbox: Literal["isolated"] = "isolated"
    risk: CapabilityRisk


class DraftValidationResult(StudioModel):
    ready: bool
    issues: tuple[ValidationIssue, ...]
    contract: EffectiveAgentContract
    manifest_yaml: str = Field(alias="manifestYaml")
    content_hash: str | None = Field(default=None, alias="contentHash")
    package_hash: str | None = Field(default=None, alias="packageHash")
