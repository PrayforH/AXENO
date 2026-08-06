from harness.policy.models import ContextTrust, ToolResultPolicyRule
from harness.policy.results import ResultPolicyEngine, stricter_trust


def test_result_policy_uses_priority_specificity_and_stable_trust_precedence() -> None:
    engine = ResultPolicyEngine(
        [
            ToolResultPolicyRule(
                name="all-mcp-sensitive",
                tool="mcp__*",
                trust=ContextTrust.SENSITIVE,
                priority=10,
            ),
            ToolResultPolicyRule(
                name="web-untrusted",
                tool="mcp__web__*",
                trust=ContextTrust.UNTRUSTED,
                priority=10,
            ),
        ]
    )

    result = engine.evaluate("mcp__web__fetch", agent_name="research")

    assert result.trust is ContextTrust.UNTRUSTED
    assert result.rule_name == "web-untrusted"
    assert stricter_trust(ContextTrust.UNTRUSTED, ContextTrust.SAFE) is ContextTrust.UNTRUSTED
