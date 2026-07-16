import pytest

from harness.policy.models import PolicyContext, PolicyDecision, PolicyRule
from harness.policy.rules import PolicyEngine, default_policy_rules
from harness.sandbox.base import SandboxIsolation


@pytest.mark.parametrize(
    ("tool", "arguments", "expected"),
    [
        ("Read", {"file_path": "/workspace/notes.txt"}, PolicyDecision.ALLOW),
        ("Task", {"subagent_type": "helper"}, PolicyDecision.ALLOW),
        ("Agent", {"subagent_type": "helper"}, PolicyDecision.ALLOW),
        (
            "mcp__harness-memory__propose_memory",
            {"content": "remember this"},
            PolicyDecision.ALLOW,
        ),
        (
            "mcp__harness-artifacts__publish_artifact",
            {"path": "outputs/report.md"},
            PolicyDecision.ALLOW,
        ),
        (
            "mcp__tavily__tavily_search",
            {"query": "current release"},
            PolicyDecision.ALLOW,
        ),
        (
            "mcp__tavily__tavily_extract",
            {"urls": ["https://example.test/source"]},
            PolicyDecision.ALLOW,
        ),
        (
            "mcp__tavily__tavily_crawl",
            {"url": "https://example.test"},
            PolicyDecision.DENY,
        ),
        ("Write", {"file_path": "/workspace/result.txt"}, PolicyDecision.ASK),
        ("Bash", {"command": "rm -rf /workspace/data"}, PolicyDecision.DENY),
    ],
)
def test_default_policy_classifies_builtin_tools(
    tool: str, arguments: dict[str, object], expected: PolicyDecision
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


@pytest.mark.parametrize(
    ("isolation", "tool", "arguments", "expected"),
    [
        (SandboxIsolation.WORKSPACE, "Read", {}, PolicyDecision.ALLOW),
        (SandboxIsolation.WORKSPACE, "Glob", {}, PolicyDecision.ALLOW),
        (SandboxIsolation.WORKSPACE, "Grep", {}, PolicyDecision.ALLOW),
        (SandboxIsolation.WORKSPACE, "Write", {}, PolicyDecision.ASK),
        (SandboxIsolation.WORKSPACE, "Edit", {}, PolicyDecision.ASK),
        (SandboxIsolation.WORKSPACE, "Bash", {"command": "pwd"}, PolicyDecision.ASK),
        (
            SandboxIsolation.WORKSPACE,
            "Bash",
            {"command": "rm -rf build"},
            PolicyDecision.DENY,
        ),
        (SandboxIsolation.CONTAINER, "Read", {}, PolicyDecision.ALLOW),
        (SandboxIsolation.CONTAINER, "Glob", {}, PolicyDecision.ALLOW),
        (SandboxIsolation.CONTAINER, "Grep", {}, PolicyDecision.ALLOW),
        (SandboxIsolation.CONTAINER, "Write", {}, PolicyDecision.ALLOW),
        (SandboxIsolation.CONTAINER, "Edit", {}, PolicyDecision.ALLOW),
        (SandboxIsolation.CONTAINER, "Bash", {"command": "pwd"}, PolicyDecision.ASK),
        (
            SandboxIsolation.CONTAINER,
            "Bash",
            {"command": "rm -rf build"},
            PolicyDecision.ASK,
        ),
        (SandboxIsolation.CONTAINER, "Unknown", {}, PolicyDecision.DENY),
    ],
)
def test_default_policy_varies_by_trusted_sandbox_isolation(
    isolation: SandboxIsolation,
    tool: str,
    arguments: dict[str, str],
    expected: PolicyDecision,
) -> None:
    result = PolicyEngine(default_policy_rules()).evaluate(
        PolicyContext(
            tenant_id="tenant-a",
            agent_name="echo-agent",
            tool_name=tool,
            arguments=arguments,
            sandbox_isolation=isolation,
        )
    )

    assert result.decision is expected


def test_isolation_rule_is_more_specific_than_generic_tool_rule() -> None:
    engine = PolicyEngine(
        [
            PolicyRule(name="write-review", tool="Write", decision=PolicyDecision.ASK),
            PolicyRule(
                name="container-write",
                tool="Write",
                sandbox_isolation=SandboxIsolation.CONTAINER,
                decision=PolicyDecision.ALLOW,
            ),
        ]
    )

    result = engine.evaluate(
        PolicyContext(
            tenant_id="tenant-a",
            agent_name="echo-agent",
            tool_name="Write",
            sandbox_isolation=SandboxIsolation.CONTAINER,
        )
    )

    assert result.rule_name == "container-write"
    assert result.decision is PolicyDecision.ALLOW


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
