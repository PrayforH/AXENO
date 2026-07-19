"""Deterministic classification for successful tool results."""

from fnmatch import fnmatch

from harness.policy.models import (
    ContextTrust,
    ToolResultPolicyResult,
    ToolResultPolicyRule,
)

_TRUST_PRECEDENCE = {
    ContextTrust.SAFE: 0,
    ContextTrust.SENSITIVE: 1,
    ContextTrust.UNTRUSTED: 2,
}


class ResultPolicyEngine:
    def __init__(self, rules: list[ToolResultPolicyRule]) -> None:
        self._rules = tuple(rules)

    def evaluate(self, tool_name: str, *, agent_name: str) -> ToolResultPolicyResult:
        matches = [
            rule
            for rule in self._rules
            if fnmatch(tool_name, rule.tool)
            and (rule.agent_name is None or rule.agent_name == agent_name)
        ]
        if not matches:
            return ToolResultPolicyResult(
                trust=ContextTrust.SAFE,
                rule_name="implicit-safe",
                reason="no tool-result policy rule matched",
            )
        selected = max(
            matches,
            key=lambda rule: (
                rule.priority,
                int(rule.agent_name is not None) + int(rule.tool != "*"),
                _TRUST_PRECEDENCE[rule.trust],
                rule.name,
            ),
        )
        return ToolResultPolicyResult(
            trust=selected.trust,
            rule_name=selected.name,
            reason=f"matched tool-result policy rule {selected.name}",
        )

    @property
    def rules(self) -> tuple[ToolResultPolicyRule, ...]:
        return self._rules


def stricter_trust(left: ContextTrust, right: ContextTrust) -> ContextTrust:
    return left if _TRUST_PRECEDENCE[left] >= _TRUST_PRECEDENCE[right] else right
