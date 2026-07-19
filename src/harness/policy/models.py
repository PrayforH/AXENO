"""Policy facts and decisions."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from harness.sandbox.base import SandboxIsolation


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class ContextTrust(StrEnum):
    """Monotonic trust level for data already present in one Run context."""

    SAFE = "safe"
    SENSITIVE = "sensitive"
    UNTRUSTED = "untrusted"


class PolicyContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    agent_name: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    sandbox_isolation: SandboxIsolation = SandboxIsolation.WORKSPACE
    context_trust: ContextTrust = ContextTrust.SAFE


class PolicyRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    decision: PolicyDecision
    tenant_id: str | None = None
    agent_name: str | None = None
    tool: str | None = None
    path_glob: str | None = None
    command_contains: str | None = None
    sandbox_isolation: SandboxIsolation | None = None
    context_trust: ContextTrust | None = None
    priority: int = 0


class PolicyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: PolicyDecision
    rule_name: str
    reason: str
