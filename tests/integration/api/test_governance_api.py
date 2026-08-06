import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app
from harness.api.dependencies import Identity, require_identity


@pytest.mark.asyncio
async def test_governance_api_connection_and_policy_publication() -> None:
    app = create_memory_app()
    app.dependency_overrides[require_identity] = lambda: Identity(
        tenant_id="tenant-a",
        user_id="owner-a",
        roles=frozenset({"owner"}),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        connection = await client.post(
            "/v1/studio/governance/connections",
            json={
                "connectionId": "personal-tavily",
                "displayName": "Personal Tavily",
                "resourceKind": "mcp",
                "resourceReference": "tavily",
                "scope": "personal",
                "principalId": "owner-a",
                "secretReference": "settings://mcp/tavily",
                "requiredKeys": ["api_key"],
            },
        )
        policy = await client.post(
            "/v1/studio/governance/policies",
            json={
                "policyId": "reviewed-tools",
                "displayName": "Reviewed tools",
                "callRules": [
                    {
                        "name": "allow-read",
                        "decision": "allow",
                        "tool": "Read",
                    }
                ],
                "resultRules": [
                    {
                        "name": "web-untrusted",
                        "trust": "untrusted",
                        "tool": "mcp__web__*",
                    }
                ],
            },
        )
        policy_payload = policy.json()
        simulation = await client.post(
            "/v1/studio/governance/policies/reviewed-tools/simulate",
            json={
                "scenario": {
                    "scenarioId": "read",
                    "agentName": "research",
                    "toolName": "Read",
                }
            },
        )
        publication = await client.post(
            "/v1/studio/governance/policies/reviewed-tools/publish",
            json={"expectedRevision": policy_payload["revision"]},
        )
        listed = await client.get("/v1/studio/governance/connections")
        rejected_secret = await client.post(
            "/v1/studio/governance/connections",
            json={
                "connectionId": "raw-secret",
                "displayName": "Raw secret",
                "resourceKind": "mcp",
                "resourceReference": "tavily",
                "scope": "personal",
                "principalId": "owner-a",
                "secretReference": "settings://mcp/tavily",
                "requiredKeys": ["api_key"],
                "secretValue": "must-never-be-accepted",
            },
        )

    assert connection.status_code == 201, connection.text
    assert "secretValue" not in connection.json()
    assert connection.json()["secretReference"] == "settings://mcp/tavily"
    assert policy.status_code == 201, policy.text
    assert simulation.status_code == 200, simulation.text
    assert simulation.json()["call"]["decision"] == "allow"
    assert simulation.json()["call"]["rule_name"] == "allow-read"
    assert publication.status_code == 200, publication.text
    assert len(publication.json()["contentHash"]) == 64
    assert listed.json()[0]["scope"] == "personal"
    assert rejected_secret.status_code == 422


@pytest.mark.asyncio
async def test_governance_mutation_requires_deployer_and_rejects_secret_values() -> None:
    app = create_memory_app()
    app.dependency_overrides[require_identity] = lambda: Identity(
        tenant_id="tenant-a",
        user_id="member-a",
        roles=frozenset({"member"}),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        denied = await client.post(
            "/v1/studio/governance/connections",
            json={
                "connectionId": "blocked",
                "displayName": "Blocked",
                "resourceKind": "mcp",
                "resourceReference": "tavily",
                "scope": "personal",
                "principalId": "member-a",
                "secretReference": "settings://mcp/tavily",
                "requiredKeys": ["api_key"],
                "secretValue": "must-never-be-accepted",
            },
        )

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "permission_denied"
