import pytest

from harness.policy.models import PolicyContext, PolicyDecision, PolicyRule
from harness.policy.rules import PolicyEngine, default_policy_rules


@pytest.mark.parametrize(
    ("tool", "arguments", "expected"),
    [
        ("Read", {"file_path": "/workspace/notes.txt"}, PolicyDecision.ALLOW),
        ("Write", {"file_path": "/workspace/result.txt"}, PolicyDecision.ASK),
        ("Bash", {"command": "rm -rf /workspace/data"}, PolicyDecision.DENY),
    ],
)
def test_default_policy_classifies_builtin_tools(
    tool: str, arguments: dict[str, str], expected: PolicyDecision
) -> None:
    engine = PolicyEngine(default_policy_rules())

    result = engine.evaluate(
        PolicyContext(
            tenant_id="tenant-a",
            agent_name="echo-agent",
            tool_name=tool,
            arguments=arguments,
        )
    )

    assert result.decision is expected


def test_more_specific_rule_wins_then_deny_wins_equal_precedence() -> None:
    engine = PolicyEngine(
        [
            PolicyRule(name="all-write", tool="Write", decision=PolicyDecision.ASK),
            PolicyRule(
                name="tenant-output",
                tenant_id="tenant-a",
                agent_name="echo-agent",
                tool="Write",
                path_glob="/workspace/output/**",
                decision=PolicyDecision.ALLOW,
            ),
            PolicyRule(
                name="protected",
                tenant_id="tenant-a",
                agent_name="echo-agent",
                tool="Write",
                path_glob="/workspace/output/secret.txt",
                decision=PolicyDecision.DENY,
            ),
        ]
    )
    context = PolicyContext(
        tenant_id="tenant-a",
        agent_name="echo-agent",
        tool_name="Write",
        arguments={"file_path": "/workspace/output/secret.txt"},
    )

    result = engine.evaluate(context)

    assert result.decision is PolicyDecision.DENY
    assert result.rule_name == "protected"
