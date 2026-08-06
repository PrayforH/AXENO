"""Immutable policy snapshot resolved once for a Run."""

from dataclasses import dataclass

from harness.policy.results import ResultPolicyEngine
from harness.policy.rules import PolicyEngine


@dataclass(frozen=True)
class ResolvedPolicy:
    policy_id: str
    revision: int | None
    content_hash: str
    call_policy: PolicyEngine
    result_policy: ResultPolicyEngine
