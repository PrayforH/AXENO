from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_app
from harness.api.dependencies import build_memory_container


@pytest.mark.asyncio
async def test_shared_agent_catalog_and_session_keep_user_owned_history_boundary() -> None:
    container = build_memory_container()
    alice_session = await container.auth.register(
        email="alice-space@example.com", password="Long-password-1", display_name="Alice"
    )
    bob_session = await container.auth.register(
        email="bob-space@example.com", password="Long-password-2", display_name="Bob"
    )
    alice_id = alice_session.user.user_id
    bob_id = bob_session.user.user_id
    version = await container.agents.publish(
        "local", alice_id, "agents/lead-agent/agent.yaml", environment="production"
    )
    app = cast(FastAPI, create_app(container))
    token = container.api_bearer_token.get_secret_value()
    base = {"Authorization": f"Bearer {token}", "X-Tenant-ID": "local"}
    alice = {**base, "X-User-ID": alice_id}
    bob = {**base, "X-User-ID": bob_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/spaces", headers=alice, json={"name": "民政协作组"}
        )
        assert created.status_code == 201
        space_id = created.json()["space"]["spaceId"]
        member = await client.put(
            f"/v1/spaces/{space_id}/members",
            headers=alice,
            json={"user_id": bob_id, "role": "viewer"},
        )
        shared = await client.post(
            f"/v1/spaces/{space_id}/agents",
            headers=alice,
            json={
                "owner_user_id": alice_id,
                "name": version.name,
                "version": version.version,
                "runnable_by_viewer": True,
            },
        )
        catalog = await client.get("/v1/agents", headers=bob)
        session = await client.post(
            "/v1/sessions",
            headers=bob,
            json={
                "agent_name": version.name,
                "agent_version": version.version,
                "agent_owner_user_id": alice_id,
                "space_id": space_id,
            },
        )
        denied = await client.post(
            "/v1/sessions",
            headers=bob,
            json={
                "agent_name": version.name,
                "agent_version": version.version,
                "agent_owner_user_id": alice_id,
            },
        )

    assert member.status_code == 200
    assert shared.status_code == 201
    team_item = next(item for item in catalog.json() if item["scope"] == "team")
    assert team_item["owner_user_id"] == alice_id
    assert team_item["space_id"] == space_id
    assert session.status_code == 201
    assert session.json()["user_id"] == bob_id
    assert session.json()["agent_owner_user_id"] == alice_id
    assert session.json()["team_ids"] == [space_id]
    assert denied.status_code == 409


@pytest.mark.asyncio
async def test_non_member_cannot_discover_space() -> None:
    container = build_memory_container()
    alice_session = await container.auth.register(
        email="alice-private-space@example.com",
        password="Long-password-1",
        display_name="Alice",
    )
    bob_session = await container.auth.register(
        email="bob-private-space@example.com",
        password="Long-password-2",
        display_name="Bob",
    )
    app = cast(FastAPI, create_app(container))
    token = container.api_bearer_token.get_secret_value()
    base = {"Authorization": f"Bearer {token}", "X-Tenant-ID": "local"}
    alice = {**base, "X-User-ID": alice_session.user.user_id}
    bob = {**base, "X-User-ID": bob_session.user.user_id}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/v1/spaces", headers=alice, json={"name": "私有协作组"})
        space_id = created.json()["space"]["spaceId"]
        hidden = await client.get(f"/v1/spaces/{space_id}", headers=bob)
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_removing_member_revokes_run_access_for_existing_shared_session() -> None:
    container = build_memory_container()
    alice_session = await container.auth.register(
        email="alice-revoke-space@example.com",
        password="Long-password-1",
        display_name="Alice",
    )
    bob_session = await container.auth.register(
        email="bob-revoke-space@example.com",
        password="Long-password-2",
        display_name="Bob",
    )
    alice_id = alice_session.user.user_id
    bob_id = bob_session.user.user_id
    version = await container.agents.publish(
        "local", alice_id, "agents/lead-agent/agent.yaml", environment="production"
    )
    app = cast(FastAPI, create_app(container))
    token = container.api_bearer_token.get_secret_value()
    base = {"Authorization": f"Bearer {token}", "X-Tenant-ID": "local"}
    alice = {**base, "X-User-ID": alice_id}
    bob = {**base, "X-User-ID": bob_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/spaces", headers=alice, json={"name": "撤权验收组"}
        )
        space_id = created.json()["space"]["spaceId"]
        await client.put(
            f"/v1/spaces/{space_id}/members",
            headers=alice,
            json={"user_id": bob_id, "role": "viewer"},
        )
        await client.post(
            f"/v1/spaces/{space_id}/agents",
            headers=alice,
            json={
                "owner_user_id": alice_id,
                "name": version.name,
                "version": version.version,
                "runnable_by_viewer": True,
            },
        )
        session = await client.post(
            "/v1/sessions",
            headers=bob,
            json={
                "agent_name": version.name,
                "agent_version": version.version,
                "agent_owner_user_id": alice_id,
                "space_id": space_id,
            },
        )
        session_id = session.json()["session_id"]
        removed = await client.delete(
            f"/v1/spaces/{space_id}/members/{bob_id}", headers=alice
        )
        run = await client.post(
            f"/v1/sessions/{session_id}/runs",
            headers={**bob, "Idempotency-Key": "revoked-member-run"},
            json={"prompt": "should be denied"},
        )

    assert removed.status_code == 204
    assert run.status_code == 404
