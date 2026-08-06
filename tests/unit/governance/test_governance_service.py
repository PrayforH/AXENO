from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from harness.core.errors import ConflictError
from harness.core.models import ExecutionIdentity
from harness.execution.credentials import (
    CredentialLeaseError,
    CredentialResourceKind,
    InMemoryCredentialBroker,
)
from harness.governance.models import (
    CreateCredentialConnectionRequest,
    CreateGovernedPolicyRequest,
    GovernedCallRule,
    GovernedResultRule,
    PolicyScenario,
    PreviewPolicyImpactRequest,
    ReplaceGovernedPolicyRequest,
)
from harness.governance.repositories import InMemoryGovernanceRepository
from harness.governance.service import GovernanceService
from harness.policy.models import ContextTrust, PolicyDecision
from harness.policy.profiles import default_policy_profiles

NOW = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)


def identity(
    user_id: str,
    *,
    team_ids: tuple[str, ...] = (),
    run_id: str = "run-a",
) -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id=user_id,
        team_ids=team_ids,
        project_id="research",
        session_id="session-a",
        run_id=run_id,
        agent_name="research",
        agent_version="1.0.0",
    )


def service() -> GovernanceService:
    return GovernanceService(
        InMemoryGovernanceRepository(),
        static_profiles=default_policy_profiles(),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_connection_scope_authorization_and_revocation_are_fail_closed() -> None:
    governance = service()
    for connection_id, scope, principal in (
        ("personal-search", "personal", "user-a"),
        ("team-search", "team", "team-red"),
        ("trigger-search", "workload", "trigger:nightly"),
    ):
        await governance.create_connection(
            "tenant-a",
            "owner-a",
            CreateCredentialConnectionRequest.model_validate(
                {
                    "connectionId": connection_id,
                    "displayName": connection_id,
                    "resourceKind": "mcp",
                    "resourceReference": "tavily",
                    "scope": scope,
                    "principalId": principal,
                    "secretReference": "settings://mcp/tavily",
                    "requiredKeys": ["api_key"],
                }
            ),
        )

    personal = await governance.authorize(
        identity("user-a"), CredentialResourceKind.MCP, "tavily"
    )
    team = await governance.authorize(
        identity("user-b", team_ids=("team-red",)),
        CredentialResourceKind.MCP,
        "tavily",
    )
    workload = await governance.authorize(
        identity("trigger:nightly"), CredentialResourceKind.MCP, "tavily"
    )

    assert personal is not None and personal.connection_id == "personal-search"
    assert team is not None and team.connection_id == "team-search"
    assert workload is not None and workload.connection_id == "trigger-search"
    with pytest.raises(CredentialLeaseError, match="not authorized"):
        await governance.authorize(
            identity("user-c"), CredentialResourceKind.MCP, "tavily"
        )

    broker = InMemoryCredentialBroker(
        {
            ("*", CredentialResourceKind.MCP, "tavily"): (
                "settings://mcp/tavily",
                {"api_key": SecretStr("secret-value")},
            )
        },
        clock=lambda: NOW,
        connection_authorizer=governance,
    )
    lease = await broker.issue(
        identity=identity("user-a"),
        resource_kind=CredentialResourceKind.MCP,
        resource_reference="tavily",
        required_keys=frozenset({"api_key"}),
    )
    assert lease.audit_record()["connection_id"] == "personal-search"

    connection = await governance.repository.get_connection(
        "tenant-a", "personal-search"
    )
    await governance.revoke_connection(
        "tenant-a",
        "owner-a",
        "personal-search",
        expected_revision=connection.revision,
    )
    with pytest.raises(CredentialLeaseError, match="no longer authorized"):
        await broker.resolve(lease.lease_id, identity("user-a"))
    with pytest.raises(CredentialLeaseError, match="not authorized"):
        await broker.issue(
            identity=identity("user-a", run_id="run-b"),
            resource_kind=CredentialResourceKind.MCP,
            resource_reference="tavily",
            required_keys=frozenset({"api_key"}),
        )


@pytest.mark.asyncio
async def test_policy_simulation_impact_and_immutable_publication() -> None:
    governance = service()
    profile = await governance.create_policy(
        "tenant-a",
        "owner-a",
        CreateGovernedPolicyRequest(
            policy_id="research-policy",
            display_name="Research policy",
            call_rules=(
                GovernedCallRule(
                    name="allow-read",
                    tool="Read",
                    decision=PolicyDecision.ALLOW,
                ),
                GovernedCallRule(
                    name="review-bash",
                    tool="Bash",
                    decision=PolicyDecision.ASK,
                ),
            ),
            result_rules=(
                GovernedResultRule(
                    name="web-is-untrusted",
                    tool="mcp__tavily__*",
                    trust=ContextTrust.UNTRUSTED,
                ),
            ),
        ),
    )
    scenario = PolicyScenario(
        scenario_id="shell",
        agent_name="research",
        tool_name="Bash",
        arguments={"command": "git status"},
    )
    simulation = await governance.simulate_draft(
        "tenant-a", profile.policy_id, scenario
    )
    assert simulation.call.decision is PolicyDecision.ASK
    assert simulation.call.rule_name == "review-bash"
    assert simulation.result.trust is ContextTrust.SAFE

    publication = await governance.publish_policy(
        "tenant-a",
        "owner-a",
        profile.policy_id,
        expected_revision=profile.revision,
    )
    resolved = await governance.resolve_runtime("tenant-a", profile.policy_id)
    assert resolved.revision == publication.revision
    assert resolved.content_hash == publication.content_hash
    assert (
        resolved.result_policy.evaluate(
            "mcp__tavily__tavily_search", agent_name="research"
        ).trust
        is ContextTrust.UNTRUSTED
    )

    updated = await governance.replace_policy(
        "tenant-a",
        "owner-a",
        profile.policy_id,
        ReplaceGovernedPolicyRequest(
            expected_revision=profile.revision,
            display_name=profile.display_name,
            call_rules=(
                GovernedCallRule(
                    name="allow-read",
                    tool="Read",
                    decision=PolicyDecision.ALLOW,
                ),
                GovernedCallRule(
                    name="deny-bash",
                    tool="Bash",
                    decision=PolicyDecision.DENY,
                ),
            ),
            result_rules=profile.result_rules,
        ),
    )
    impact = await governance.preview_impact(
        "tenant-a",
        profile.policy_id,
        PreviewPolicyImpactRequest(scenarios=(scenario,)),
    )
    assert impact.changed_count == 1
    assert impact.items[0].before.call.decision is PolicyDecision.ASK
    assert impact.items[0].after.call.decision is PolicyDecision.DENY
    assert (
        await governance.repository.get_publication(
            "tenant-a", profile.policy_id, publication.revision
        )
    ) == publication

    with pytest.raises(ConflictError, match="revision changed"):
        await governance.publish_policy(
            "tenant-a",
            "owner-a",
            profile.policy_id,
            expected_revision=profile.revision,
        )
    assert updated.revision == 2
