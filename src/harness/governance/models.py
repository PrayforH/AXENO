from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.execution.credentials import CredentialResourceKind
from harness.policy.models import (
    ContextTrust,
    PolicyDecision,
    PolicyResult,
    PolicyRule,
    ToolResultPolicyResult,
    ToolResultPolicyRule,
)
from harness.sandbox.base import SandboxIsolation


def _to_camel(value: str) -> str:
    return re.sub(r"_([a-z])", lambda match: match.group(1).upper(), value)


class GovernanceModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        alias_generator=_to_camel,
        extra="forbid",
    )


class ConnectionScope(StrEnum):
    PERSONAL = "personal"
    TEAM = "team"
    WORKLOAD = "workload"


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class CredentialConnection(GovernanceModel):
    tenant_id: str = Field(min_length=1)
    connection_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=160)
    resource_kind: CredentialResourceKind
    resource_reference: str = Field(min_length=1, max_length=256)
    scope: ConnectionScope
    principal_id: str = Field(min_length=1, max_length=256)
    secret_reference: str = Field(min_length=1, max_length=1_000)
    required_keys: tuple[str, ...] = ()
    status: ConnectionStatus = ConnectionStatus.ACTIVE
    revision: int = Field(ge=1)
    created_by: str = Field(min_length=1)
    updated_by: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def valid_keys_and_status(self) -> CredentialConnection:
        if len(set(self.required_keys)) != len(self.required_keys):
            raise ValueError("credential connection contains duplicate required keys")
        if any(not key or len(key) > 128 for key in self.required_keys):
            raise ValueError("credential connection required keys must be 1-128 characters")
        if self.status is ConnectionStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked credential connection requires revokedAt")
        if self.status is ConnectionStatus.ACTIVE and self.revoked_at is not None:
            raise ValueError("active credential connection cannot have revokedAt")
        return self


class CreateCredentialConnectionRequest(GovernanceModel):
    connection_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=160)
    resource_kind: CredentialResourceKind
    resource_reference: str = Field(min_length=1, max_length=256)
    scope: ConnectionScope
    principal_id: str = Field(min_length=1, max_length=256)
    secret_reference: str = Field(min_length=1, max_length=1_000)
    required_keys: tuple[str, ...] = ()


class ReplaceCredentialConnectionRequest(GovernanceModel):
    expected_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=160)
    secret_reference: str = Field(min_length=1, max_length=1_000)
    required_keys: tuple[str, ...] = ()


class RevokeCredentialConnectionRequest(GovernanceModel):
    expected_revision: int = Field(ge=1)


class GovernedCallRule(GovernanceModel):
    name: str = Field(min_length=1, max_length=160)
    decision: PolicyDecision
    tenant_id: str | None = None
    agent_name: str | None = None
    tool: str | None = None
    path_glob: str | None = None
    command_contains: str | None = None
    sandbox_isolation: SandboxIsolation | None = None
    context_trust: ContextTrust | None = None
    priority: int = 0

    def to_policy_rule(self) -> PolicyRule:
        return PolicyRule.model_validate(self.model_dump())


class GovernedResultRule(GovernanceModel):
    name: str = Field(min_length=1, max_length=160)
    trust: ContextTrust
    tool: str = "*"
    agent_name: str | None = None
    priority: int = 0

    def to_policy_rule(self) -> ToolResultPolicyRule:
        return ToolResultPolicyRule.model_validate(self.model_dump())


class GovernedPolicyProfile(GovernanceModel):
    tenant_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1_000)
    call_rules: tuple[GovernedCallRule, ...] = ()
    result_rules: tuple[GovernedResultRule, ...] = ()
    revision: int = Field(ge=1)
    published_revision: int | None = Field(default=None, ge=1)
    published_hash: str | None = Field(default=None, min_length=64, max_length=64)
    created_by: str = Field(min_length=1)
    updated_by: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def unique_rule_names(self) -> GovernedPolicyProfile:
        names = [rule.name for rule in (*self.call_rules, *self.result_rules)]
        if len(set(names)) != len(names):
            raise ValueError("governed policy rule names must be unique")
        if (self.published_revision is None) != (self.published_hash is None):
            raise ValueError("published revision and hash must be set together")
        return self


class CreateGovernedPolicyRequest(GovernanceModel):
    policy_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1_000)
    call_rules: tuple[GovernedCallRule, ...] = ()
    result_rules: tuple[GovernedResultRule, ...] = ()


class ReplaceGovernedPolicyRequest(GovernanceModel):
    expected_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1_000)
    call_rules: tuple[GovernedCallRule, ...] = ()
    result_rules: tuple[GovernedResultRule, ...] = ()


class PolicyPublication(GovernanceModel):
    tenant_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    display_name: str
    description: str = ""
    call_rules: tuple[GovernedCallRule, ...] = ()
    result_rules: tuple[GovernedResultRule, ...] = ()
    published_by: str = Field(min_length=1)
    published_at: datetime


class PublishGovernedPolicyRequest(GovernanceModel):
    expected_revision: int = Field(ge=1)


class PolicyScenario(GovernanceModel):
    scenario_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=512)
    arguments: dict[str, object] = Field(default_factory=dict)
    sandbox_isolation: SandboxIsolation = SandboxIsolation.WORKSPACE
    context_trust: ContextTrust = ContextTrust.SAFE


class SimulateGovernedPolicyRequest(GovernanceModel):
    scenario: PolicyScenario


class PolicySimulationResult(GovernanceModel):
    scenario_id: str
    call: PolicyResult
    result: ToolResultPolicyResult


class PreviewPolicyImpactRequest(GovernanceModel):
    scenarios: tuple[PolicyScenario, ...] = Field(min_length=1, max_length=100)


class PolicyImpactItem(GovernanceModel):
    scenario_id: str
    before: PolicySimulationResult
    after: PolicySimulationResult
    changed: bool


class PolicyImpactPreview(GovernanceModel):
    policy_id: str
    draft_revision: int
    published_revision: int | None = None
    scenario_count: int
    changed_count: int
    items: tuple[PolicyImpactItem, ...]
