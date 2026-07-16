"""Immutable models used by the Agent Studio authoring control plane."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    subagents: tuple[DraftSubagent, ...] = ()
    permission_policy: str = Field(alias="permissionPolicy", min_length=1)
    workspace: DraftWorkspace = DraftWorkspace()
    limits: DraftLimits = DraftLimits()
    evaluation_cases: tuple[EvalCase, ...] = Field(
        min_length=1, alias="evaluationCases"
    )

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
        duplicate_aliases = sorted(
            {alias for alias in aliases if aliases.count(alias) > 1}
        )
        if duplicate_aliases:
            raise ValueError(
                f"duplicate subagent alias: {', '.join(duplicate_aliases)}"
            )
        skill_names = [skill.name for skill in self.skills]
        duplicate_skills = sorted(
            {name for name in skill_names if skill_names.count(name) > 1}
        )
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


class CreateAgentDraftRequest(StudioModel):
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    domain: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(alias="displayName", min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    template: AgentTemplate = AgentTemplate.ANALYST


class ReplaceAgentDraftRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    spec: AgentDraftSpec


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
    capabilities: frozenset[str]
    credential_managed: bool = Field(default=True, alias="credentialManaged")


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


class PolicyCapability(StudioModel):
    policy_id: str = Field(alias="policyId")
    label: str
    description: str
    risk: CapabilityRisk


class TemplateCapability(StudioModel):
    template: AgentTemplate
    label: str
    description: str


class CapabilityCatalog(StudioModel):
    model_routes: tuple[ModelRouteCapability, ...] = Field(alias="modelRoutes")
    builtin_tools: tuple[BuiltinToolCapability, ...] = Field(alias="builtinTools")
    mcp_servers: tuple[McpCapability, ...] = Field(alias="mcpServers")
    policies: tuple[PolicyCapability, ...]
    templates: tuple[TemplateCapability, ...]


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
