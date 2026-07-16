import hashlib
from dataclasses import replace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from harness.adapters.memory import InMemoryAgentRegistry
from harness.api.app import create_app
from harness.api.dependencies import ApiContainer, build_memory_container

SERVICE_TOKEN = "studio-service-token-with-at-least-32-characters"


def app() -> FastAPI:
    container = replace(
        build_memory_container(),
        environment="production",
        api_bearer_token=SecretStr(SERVICE_TOKEN),
    )
    return create_app(container)


def app_and_container() -> tuple[FastAPI, ApiContainer]:
    container = replace(
        build_memory_container(),
        environment="production",
        api_bearer_token=SecretStr(SERVICE_TOKEN),
    )
    return create_app(container), container


async def register(client: AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "SecurePass123",
            "display_name": "Studio Builder",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def draft_request(name: str = "policy-researcher") -> dict[str, str]:
    return {
        "name": name,
        "domain": "policy-research",
        "displayName": "政策研究助手",
        "description": "整理政策材料并输出有出处的研究结论。",
        "template": "analyst",
    }


@pytest.mark.asyncio
async def test_studio_rejects_unauthenticated_and_self_reported_identity() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        anonymous = await client.get("/v1/studio/capabilities")
        spoofed = await client.get(
            "/v1/studio/capabilities",
            headers={"X-Tenant-ID": "tenant-evil", "X-User-ID": "user-evil"},
        )

    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "api_auth_required"
    assert spoofed.status_code == 401
    assert spoofed.json()["error"]["code"] == "api_auth_required"


@pytest.mark.asyncio
async def test_service_identity_can_build_and_publish_existing_bundle() -> None:
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "builder-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        capabilities = await client.get("/v1/studio/capabilities", headers=headers)
        created = await client.post(
            "/v1/studio/drafts", headers=headers, json=draft_request()
        )
        draft_id = created.json()["draftId"]
        validation = await client.post(
            f"/v1/studio/drafts/{draft_id}/validate", headers=headers
        )
        bundle = await client.get(
            f"/v1/studio/drafts/{draft_id}/bundle", headers=headers
        )
        published = await client.post(
            f"/v1/studio/drafts/{draft_id}/publish", headers=headers
        )
        drafts = await client.get("/v1/studio/drafts", headers=headers)

    assert capabilities.status_code == 200
    assert capabilities.json()["mcpServers"][0]["reference"] == "tavily-readonly"
    assert created.status_code == 201
    assert created.json()["tenantId"] == "tenant-a"
    assert created.json()["createdBy"] == "builder-a"
    assert validation.status_code == 200
    assert validation.json()["ready"] is True
    assert validation.json()["contract"]["sandbox"] == "isolated"
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"
    content_hash = validation.json()["contentHash"]
    package_hash = validation.json()["packageHash"]
    assert bundle.headers["content-disposition"] == (
        "attachment; "
        f'filename="policy-researcher-0.1.0-{package_hash[:12]}.zip"'
    )
    archive_hash = hashlib.sha256(bundle.content).hexdigest()
    assert bundle.headers["etag"] == f'"{archive_hash}"'
    assert bundle.headers["x-agent-content-sha256"] == content_hash
    assert bundle.headers["x-agent-package-sha256"] == package_hash
    assert published.status_code == 200
    assert published.json()["name"] == "policy-researcher"
    assert drafts.json()[0]["publishedVersion"] == "0.1.0"


@pytest.mark.asyncio
async def test_jwt_identity_ignores_spoofed_tenant_and_user_headers() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        owner = await register(client, "owner@example.com")
        body_spoofed = await client.post(
            "/v1/studio/drafts",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
            json={
                **draft_request(),
                "tenantId": "tenant-evil",
                "createdBy": "user-evil",
            },
        )
        created = await client.post(
            "/v1/studio/drafts",
            headers={
                "Authorization": f"Bearer {owner['access_token']}",
                "X-Tenant-ID": "tenant-evil",
                "X-User-ID": "user-evil",
            },
            json=draft_request(),
        )

    assert body_spoofed.status_code == 422
    assert created.status_code == 201
    assert created.json()["tenantId"] == owner["membership"]["tenant_id"]
    assert created.json()["createdBy"] == owner["user"]["user_id"]
    assert created.json()["tenantId"] != "tenant-evil"
    assert created.json()["createdBy"] != "user-evil"


@pytest.mark.asyncio
async def test_member_can_write_and_validate_but_cannot_publish() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        await register(client, "owner@example.com")
        member = await register(client, "member@example.com")
        headers = {"Authorization": f"Bearer {member['access_token']}"}
        created = await client.post(
            "/v1/studio/drafts", headers=headers, json=draft_request()
        )
        draft_id = created.json()["draftId"]
        validation = await client.post(
            f"/v1/studio/drafts/{draft_id}/validate", headers=headers
        )
        published = await client.post(
            f"/v1/studio/drafts/{draft_id}/publish", headers=headers
        )

    assert member["membership"]["role"] == "member"
    assert created.status_code == 201
    assert validation.status_code == 200
    assert published.status_code == 403
    assert published.json()["error"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_catalog_is_admin_managed_secret_free_and_drives_live_validation() -> None:
    owner_headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "owner-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        await register(client, "owner@example.com")
        member = await register(client, "member@example.com")
        member_headers = {"Authorization": f"Bearer {member['access_token']}"}
        catalog = await client.get("/v1/studio/catalog", headers=owner_headers)
        created = await client.post(
            "/v1/studio/drafts", headers=owner_headers, json=draft_request()
        )
        draft_id = created.json()["draftId"]

        rejected_secret = catalog.json()["catalog"]
        rejected_secret["modelRoutes"][0]["apiKey"] = "must-never-be-stored"
        rejected_secret["mcpServers"][0]["url"] = "https://unreviewed.example/mcp"
        secret_response = await client.put(
            "/v1/studio/catalog",
            headers=owner_headers,
            json={"expectedRevision": 1, "catalog": rejected_secret},
        )
        member_response = await client.put(
            "/v1/studio/catalog",
            headers=member_headers,
            json={"expectedRevision": 1, "catalog": catalog.json()["catalog"]},
        )
        member_registration = await client.put(
            "/v1/studio/catalog/policy/member-policy",
            headers=member_headers,
            json={
                "expectedRevision": 1,
                "resource": {
                    "policyId": "member-policy",
                    "label": "越权策略",
                    "description": "普通 Builder 不得创建。",
                    "risk": "low",
                },
            },
        )
        disabled = await client.delete(
            "/v1/studio/catalog/modelRoute/new-api-default",
            headers=owner_headers,
            params={"expected_revision": 1},
        )
        validation = await client.post(
            f"/v1/studio/drafts/{draft_id}/validate", headers=owner_headers
        )
        current = await client.get("/v1/studio/catalog", headers=owner_headers)
        member_catalog = await client.get(
            "/v1/studio/catalog", headers=member_headers
        )

    assert catalog.status_code == 200
    assert catalog.json()["revision"] == 1
    assert secret_response.status_code == 422
    assert secret_response.json()["error"]["code"] == "request_invalid"
    assert "must-never-be-stored" not in secret_response.text
    assert "unreviewed.example" not in secret_response.text
    assert "must-never-be-stored" not in current.text
    assert "unreviewed.example" not in current.text
    assert member_response.status_code == 403
    assert member_response.json()["error"]["code"] == "permission_denied"
    assert member_registration.status_code == 403
    assert member_registration.json()["error"]["code"] == "permission_denied"
    assert disabled.status_code == 200
    assert disabled.json()["record"]["revision"] == 2
    assert disabled.json()["impact"]["draftIds"] == [draft_id]
    assert validation.status_code == 200
    assert validation.json()["ready"] is False
    assert {issue["code"] for issue in validation.json()["issues"]} >= {
        "model_route_disabled"
    }
    assert current.status_code == 200
    assert current.json()["revision"] == 2
    assert member_catalog.status_code == 200
    assert member_catalog.json()["tenantId"] == member["membership"]["tenant_id"]


@pytest.mark.asyncio
async def test_published_agent_version_is_immutable_after_catalog_change() -> None:
    application, container = app_and_container()
    owner_headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "owner-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/studio/drafts", headers=owner_headers, json=draft_request()
        )
        published = await client.post(
            f"/v1/studio/drafts/{created.json()['draftId']}/publish",
            headers=owner_headers,
        )
        registry = cast(InMemoryAgentRegistry, vars(container.agents)["_registry"])
        stored_before = await registry.get(
            "tenant-a", "policy-researcher", "0.1.0"
        )
        disabled = await client.delete(
            "/v1/studio/catalog/modelRoute/new-api-default",
            headers=owner_headers,
            params={"expected_revision": 1},
        )
        stored_after = await registry.get(
            "tenant-a", "policy-researcher", "0.1.0"
        )

    assert published.status_code == 200
    assert disabled.status_code == 200
    assert stored_after == stored_before
    assert stored_after.manifest_hash == published.json()["manifest_hash"]


@pytest.mark.asyncio
async def test_admin_can_create_update_and_disable_catalog_registration() -> None:
    owner_headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "owner-a",
    }
    resource = {
        "policyId": "regulated-review",
        "label": "受监管审查",
        "description": "对受监管材料使用更严格的审批边界。",
        "risk": "high",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        created = await client.put(
            "/v1/studio/catalog/policy/regulated-review",
            headers=owner_headers,
            json={"expectedRevision": 1, "resource": resource},
        )
        created_policy = next(
            item
            for item in created.json()["record"]["catalog"]["policies"]
            if item["policyId"] == "regulated-review"
        )
        updated_resource = {**created_policy, "label": "受监管材料审查"}
        updated = await client.put(
            "/v1/studio/catalog/policy/regulated-review",
            headers=owner_headers,
            json={"expectedRevision": 2, "resource": updated_resource},
        )
        disabled = await client.delete(
            "/v1/studio/catalog/policy/regulated-review",
            headers=owner_headers,
            params={"expected_revision": 3},
        )

    assert created.status_code == 200
    assert created.json()["record"]["revision"] == 2
    assert created_policy["version"] == 1
    assert updated.status_code == 200
    updated_policy = next(
        item
        for item in updated.json()["record"]["catalog"]["policies"]
        if item["policyId"] == "regulated-review"
    )
    assert updated_policy["version"] == 2
    assert updated_policy["label"] == "受监管材料审查"
    assert disabled.status_code == 200
    disabled_policy = next(
        item
        for item in disabled.json()["record"]["catalog"]["policies"]
        if item["policyId"] == "regulated-review"
    )
    assert disabled_policy["enabled"] is False
    assert disabled_policy["version"] == 3


@pytest.mark.asyncio
async def test_studio_contract_hides_tenants_and_reports_conflict_and_invalid_bundle() -> None:
    tenant_a = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "builder-a",
    }
    tenant_b = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-b",
        "X-User-ID": "builder-b",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/studio/drafts", headers=tenant_a, json=draft_request()
        )
        draft_id = created.json()["draftId"]
        hidden = await client.get(
            f"/v1/studio/drafts/{draft_id}", headers=tenant_b
        )

        first_spec = created.json()["spec"]
        first_spec["description"] = "第一次保存。"
        first_update = await client.put(
            f"/v1/studio/drafts/{draft_id}",
            headers=tenant_a,
            json={"expectedRevision": 1, "spec": first_spec},
        )
        stale = await client.put(
            f"/v1/studio/drafts/{draft_id}",
            headers=tenant_a,
            json={"expectedRevision": 1, "spec": first_spec},
        )

        invalid_spec = first_update.json()["spec"]
        invalid_spec["builtinTools"] = [*invalid_spec["builtinTools"], "UnknownTool"]
        invalid_update = await client.put(
            f"/v1/studio/drafts/{draft_id}",
            headers=tenant_a,
            json={"expectedRevision": 2, "spec": invalid_spec},
        )
        invalid_bundle = await client.get(
            f"/v1/studio/drafts/{draft_id}/bundle", headers=tenant_a
        )

    assert created.status_code == 201
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "not_found"
    assert first_update.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "draft_conflict"
    assert invalid_update.status_code == 200
    assert invalid_bundle.status_code == 422
    assert invalid_bundle.json()["error"]["code"] == "draft_not_ready"


def test_studio_routes_are_exposed_once_in_openapi() -> None:
    schema = app().openapi()
    expected = {
        "/v1/studio/capabilities",
        "/v1/studio/drafts",
        "/v1/studio/drafts/{draft_id}",
        "/v1/studio/drafts/{draft_id}/validate",
        "/v1/studio/drafts/{draft_id}/bundle",
        "/v1/studio/drafts/{draft_id}/publish",
    }

    assert expected <= set(schema["paths"])
    assert schema["paths"]["/v1/studio/drafts"]["post"]["responses"].keys() >= {
        "201",
        "422",
    }
