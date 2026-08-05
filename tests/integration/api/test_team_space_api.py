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


@pytest.mark.asyncio
async def test_workspace_agent_releases_promote_and_acl_endpoints() -> None:
    container = build_memory_container()
    alice_session = await container.auth.register(
        email="alice-release@example.com", password="Long-password-1", display_name="Alice"
    )
    bob_session = await container.auth.register(
        email="bob-release@example.com", password="Long-password-2", display_name="Bob"
    )
    alice_id = alice_session.user.user_id
    bob_id = bob_session.user.user_id
    version_v1 = await container.agents.publish(
        "local", alice_id, "agents/lead-agent/agent.yaml", environment="production"
    )
    app = cast(FastAPI, create_app(container))
    token = container.api_bearer_token.get_secret_value()
    base = {"Authorization": f"Bearer {token}", "X-Tenant-ID": "local"}
    alice = {**base, "X-User-ID": alice_id}
    bob = {**base, "X-User-ID": bob_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/v1/spaces", headers=alice, json={"name": "发布验收组"})
        space_id = created.json()["space"]["spaceId"]
        await client.put(
            f"/v1/spaces/{space_id}/members",
            headers=alice,
            json={"user_id": bob_id, "role": "viewer"},
        )
        shared = await client.post(
            f"/v1/spaces/{space_id}/agents",
            headers=alice,
            json={
                "owner_user_id": alice_id,
                "name": version_v1.name,
                "version": version_v1.version,
                "runnable_by_viewer": False,
            },
        )
        assert shared.status_code == 201
        agent_id = shared.json()["release"]["agentId"]
        assert shared.json()["agent"]["agent_id"] == agent_id

        agents = await client.get(f"/v1/spaces/{space_id}/agents", headers=bob)
        assert agents.status_code == 200
        viewer_item = next(item for item in agents.json() if item["agent"]["agentId"] == agent_id)
        assert viewer_item["can_view"] is True
        assert viewer_item["can_chat"] is False
        assert viewer_item["can_manage"] is False

        # ACL grants chat to the viewer even with runnable_by_viewer=false.
        acl = await client.put(
            f"/v1/spaces/{space_id}/agents/{agent_id}/acl",
            headers=alice,
            json={"grantee_type": "user", "grantee_id": bob_id, "permission": "chat"},
        )
        assert acl.status_code == 201
        session = await client.post(
            "/v1/sessions",
            headers=bob,
            json={
                "agent_name": version_v1.name,
                "agent_version": version_v1.version,
                "agent_owner_user_id": alice_id,
                "space_id": space_id,
            },
        )
        assert session.status_code == 201

        # Release history lists the shared immutable version.
        releases = await client.get(
            f"/v1/spaces/{space_id}/agents/{agent_id}/releases", headers=bob
        )
        assert releases.status_code == 200
        assert [item["release"]["version"] for item in releases.json()] == [version_v1.version]

        # Promote is allowed for the owner and refuses viewers/contributors of
        # someone else's release.
        denied = await client.post(
            f"/v1/spaces/{space_id}/agents/{agent_id}/releases/{version_v1.version}/promote",
            headers=bob,
        )
        assert denied.status_code == 403
        promoted = await client.post(
            f"/v1/spaces/{space_id}/agents/{agent_id}/releases/{version_v1.version}/promote",
            headers=alice,
        )
        assert promoted.status_code == 200
        assert promoted.json()["agent"]["currentVersion"] == version_v1.version

        # Deleting the ACL row revokes the viewer chat grant again.
        removed_acl = await client.delete(
            f"/v1/spaces/{space_id}/agents/{agent_id}/acl/user/{bob_id}/chat",
            headers=alice,
        )
        assert removed_acl.status_code == 204
        denied_session = await client.post(
            "/v1/sessions",
            headers=bob,
            json={
                "agent_name": version_v1.name,
                "agent_version": version_v1.version,
                "agent_owner_user_id": alice_id,
                "space_id": space_id,
            },
        )
        assert denied_session.status_code == 403


@pytest.mark.asyncio
async def test_agent_transfer_and_draft_etag_endpoints() -> None:
    container = build_memory_container()
    alice_session = await container.auth.register(
        email="alice-transfer@example.com", password="Long-password-1", display_name="Alice"
    )
    bob_session = await container.auth.register(
        email="bob-transfer@example.com", password="Long-password-2", display_name="Bob"
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
        # Draft GET returns an ETag and PUT with a stale If-Match fails 412.
        created = await client.post(
            "/v1/studio/drafts",
            headers=alice,
            json={
                "name": "transfer-agent",
                "domain": "transfer",
                "display_name": "Transfer Agent",
                "description": "transfer test",
                "template": "analyst",
            },
        )
        assert created.status_code == 201
        draft_id = created.json()["draftId"]
        fetched = await client.get(f"/v1/studio/drafts/{draft_id}", headers=alice)
        assert fetched.headers.get("etag") == '"rev-1"'
        stale = await client.put(
            f"/v1/studio/drafts/{draft_id}",
            headers={**alice, "If-Match": '"rev-99"'},
            json={
                "expectedRevision": 1,
                "spec": created.json()["spec"],
            },
        )
        assert stale.status_code == 412
        fresh = await client.put(
            f"/v1/studio/drafts/{draft_id}",
            headers={**alice, "If-Match": '"rev-1"'},
            json={
                "expectedRevision": 1,
                "spec": created.json()["spec"],
            },
        )
        assert fresh.status_code == 200
        assert fresh.headers.get("etag") == '"rev-2"'

        # Only the owner can transfer; the new owner inherits the catalog row.
        personal_agent_id = version.agent_id
        assert personal_agent_id is not None
        denied = await client.post(
            f"/v1/agents/{personal_agent_id}/transfer",
            headers=bob,
            json={"to_user_id": bob_id},
        )
        assert denied.status_code == 403
        transferred = await client.post(
            f"/v1/agents/{personal_agent_id}/transfer",
            headers=alice,
            json={"to_user_id": bob_id},
        )
        assert transferred.status_code == 200
        assert transferred.json()["ownerUserId"] == bob_id
        assert transferred.json()["agentId"] == personal_agent_id
        # The immutable version moved with the identity.
        catalog = await client.get("/v1/agents", headers=bob)
        assert any(
            item["name"] == version.name and item["agent_id"] == personal_agent_id
            for item in catalog.json()
        )

        # User group management endpoints.
        group = await client.post(
            "/v1/groups",
            headers=alice,
            json={"name": "transfer-group", "description": ""},
        )
        assert group.status_code == 201
        group_id = group.json()["groupId"]
        member = await client.put(
            f"/v1/groups/{group_id}/members",
            headers=alice,
            json={"user_id": bob_id},
        )
        assert member.status_code == 201
        removed = await client.delete(
            f"/v1/groups/{group_id}/members/{bob_id}", headers=alice
        )
        assert removed.status_code == 204
        deleted = await client.delete(f"/v1/groups/{group_id}", headers=alice)
        assert deleted.status_code == 204

