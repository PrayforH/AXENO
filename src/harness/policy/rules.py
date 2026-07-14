"""Deterministic matching and precedence for policy rules."""

from fnmatch import fnmatch

from harness.policy.models import PolicyContext, PolicyDecision, PolicyResult, PolicyRule
from harness.sandbox.base import SandboxIsolation

_DECISION_PRECEDENCE = {
    PolicyDecision.ALLOW: 0,
    PolicyDecision.ASK: 1,
    PolicyDecision.DENY: 2,
}


def _path(context: PolicyContext) -> str:
    value = context.arguments.get("file_path", context.arguments.get("path", ""))
    return str(value)


def _matches(rule: PolicyRule, context: PolicyContext) -> bool:
    if rule.tenant_id is not None and rule.tenant_id != context.tenant_id:
        return False
    if rule.agent_name is not None and rule.agent_name != context.agent_name:
        return False
    if rule.tool is not None and rule.tool != context.tool_name:
        return False
    if (
        rule.sandbox_isolation is not None
        and rule.sandbox_isolation is not context.sandbox_isolation
    ):
        return False
    if rule.path_glob is not None and not fnmatch(_path(context), rule.path_glob):
        return False
    if rule.command_contains is not None:
        command = str(context.arguments.get("command", ""))
        if rule.command_contains not in command:
            return False
    return True


def _specificity(rule: PolicyRule) -> int:
    return sum(
        field is not None
        for field in (
            rule.tenant_id,
            rule.agent_name,
            rule.tool,
            rule.path_glob,
            rule.command_contains,
            rule.sandbox_isolation,
        )
    )


class PolicyEngine:
    def __init__(self, rules: list[PolicyRule]) -> None:
        self._rules = tuple(rules)

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        matches = [rule for rule in self._rules if _matches(rule, context)]
        if not matches:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                rule_name="implicit-deny",
                reason="no policy rule matched",
            )
        selected = max(
            matches,
            key=lambda rule: (
                rule.priority,
                _specificity(rule),
                _DECISION_PRECEDENCE[rule.decision],
                rule.name,
            ),
        )
        return PolicyResult(
            decision=selected.decision,
            rule_name=selected.name,
            reason=f"matched policy rule {selected.name}",
        )


def default_policy_rules() -> list[PolicyRule]:
    return [
        PolicyRule(name="read", tool="Read", decision=PolicyDecision.ALLOW),
        PolicyRule(name="glob", tool="Glob", decision=PolicyDecision.ALLOW),
        PolicyRule(name="grep", tool="Grep", decision=PolicyDecision.ALLOW),
        PolicyRule(name="delegate", tool="Task", decision=PolicyDecision.ALLOW),
        PolicyRule(name="delegate-agent", tool="Agent", decision=PolicyDecision.ALLOW),
        PolicyRule(
            name="harness-memory-update",
            tool="mcp__harness-memory__update_user_memory",
            decision=PolicyDecision.ALLOW,
        ),
        PolicyRule(
            name="harness-artifact-publish",
            tool="mcp__harness-artifacts__publish_artifact",
            decision=PolicyDecision.ALLOW,
        ),
        PolicyRule(
            name="tavily-search",
            tool="mcp__tavily__tavily_search",
            decision=PolicyDecision.ALLOW,
        ),
        PolicyRule(
            name="tavily-extract",
            tool="mcp__tavily__tavily_extract",
            decision=PolicyDecision.ALLOW,
        ),
        PolicyRule(name="write-review", tool="Write", decision=PolicyDecision.ASK),
        PolicyRule(name="edit-review", tool="Edit", decision=PolicyDecision.ASK),
        PolicyRule(
            name="container-write",
            tool="Write",
            sandbox_isolation=SandboxIsolation.CONTAINER,
            decision=PolicyDecision.ALLOW,
        ),
        PolicyRule(
            name="container-edit",
            tool="Edit",
            sandbox_isolation=SandboxIsolation.CONTAINER,
            decision=PolicyDecision.ALLOW,
        ),
        PolicyRule(
            name="destructive-rm",
            tool="Bash",
            command_contains="rm ",
            sandbox_isolation=SandboxIsolation.WORKSPACE,
            decision=PolicyDecision.DENY,
        ),
        PolicyRule(name="bash-review", tool="Bash", decision=PolicyDecision.ASK),
    ]
