"""Policy facts and decisions."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PolicyContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    agent_name: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class PolicyRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    decision: PolicyDecision
    tenant_id: str | None = None
    agent_name: str | None = None
    tool: str | None = None
    path_glob: str | None = None
    command_contains: str | None = None
    priority: int = 0


class PolicyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: PolicyDecision
    rule_name: str
    reason: str
