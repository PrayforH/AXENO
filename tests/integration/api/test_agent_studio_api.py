import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, cast
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from harness.adapters.memory import InMemoryAgentRegistry
from harness.api.app import create_app
from harness.api.dependencies import ApiContainer, build_memory_container
from harness.auth.models import Membership
from harness.auth.repositories import InMemoryAuthRepository
from harness.core.errors import NotFoundError
from harness.core.manifest import ToolDirectorySnapshot
from harness.evals.models import EvalRunStatus
from harness.quota.models import QuotaResource, ReplaceQuotaPolicyRequest
from harness.studio.mcp_discovery import (
    DiscoveredServer,
    McpDiscoveryService,
)

SERVICE_TOKEN = "studio-service-token-with-at-least-32-characters"


def app() -> FastAPI:
    container = replace(
        build_memory_container(),
        environment="production",
        api_bearer_token=SecretStr(SERVICE_TOKEN),
    )
    return create_app(container)


def app_and_container(*, auto_execute: bool = False) -> tuple[FastAPI, ApiContainer]:
    container = replace(
        build_memory_container(auto_execute=auto_execute),
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


async def drain_eval(container: ApiContainer, eval_run_id: str) -> None:
    for _ in range(40):
        await container.eval_controller.process_once()
        task = await container.task_queue.dequeue()
        if task is not None:
            await container.worker.execute(task.tenant_id, task.run_id)
            await container.task_queue.acknowledge(task)
        current = await container.eval_run_repository.get("tenant-a", eval_run_id)
        if current.status.is_terminal:
            return
    raise AssertionError("Eval Run did not converge")


@pytest.mark.asyncio
async def test_studio_rejects_unauthenticated_and_self_reported_identity() -> None:
    async with AsyncClient(transport=ASGITransport(app=app()), base_url="http://test") as client:
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
    async with AsyncClient(transport=ASGITransport(app=app()), base_url="http://test") as client:
        capabilities = await client.get("/v1/studio/capabilities", headers=headers)
        created = await client.post("/v1/studio/drafts", headers=headers, json=draft_request())
        draft_id = created.json()["draftId"]
        validation = await client.post(f"/v1/studio/drafts/{draft_id}/validate", headers=headers)
        bundle = await client.get(f"/v1/studio/drafts/{draft_id}/bundle", headers=headers)
        published = await client.post(f"/v1/studio/drafts/{draft_id}/publish", headers=headers)
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
        f'attachment; filename="policy-researcher-0.1.0-{package_hash[:12]}.zip"'
    )
    archive_hash = hashlib.sha256(bundle.content).hexdigest()
    assert bundle.headers["etag"] == f'"{archive_hash}"'
    assert bundle.headers["x-agent-content-sha256"] == content_hash
    assert bundle.headers["x-agent-package-sha256"] == package_hash
    assert published.status_code == 200
    assert published.json()["name"] == "policy-researcher"
    assert "snapshot" not in published.json()
    assert drafts.json()[0]["publishedVersion"] == "0.1.0"


@pytest.mark.asyncio
async def test_studio_api_round_trips_and_bundles_on_demand_tool_directory() -> None:
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "builder-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app()),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/v1/studio/drafts",
            headers=headers,
            json=draft_request("on-demand-agent"),
        )
        spec = created.json()["spec"]
        spec["model"] = {
            **spec["model"],
            "routeId": "anthropic-official",
            "model": "claude-sonnet-4-6",
            "requiredCapabilities": [
                "streaming",
                "tool_use",
                "tool_search",
            ],
        }
        spec["mcpServers"] = ["tavily-readonly"]
        spec["toolExposureMode"] = "on_demand"
        replaced = await client.put(
            f"/v1/studio/drafts/{created.json()['draftId']}",
            headers=headers,
            json={"expectedRevision": 1, "spec": spec},
        )
        validation = await client.post(
            f"/v1/studio/drafts/{created.json()['draftId']}/validate",
            headers=headers,
        )
        bundle = await client.get(
            f"/v1/studio/drafts/{created.json()['draftId']}/bundle",
            headers=headers,
        )

    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["spec"]["toolExposureMode"] == "on_demand"
    assert validation.status_code == 200, validation.text
    assert validation.json()["ready"] is True
    assert validation.json()["contract"]["toolExposureMode"] == "on_demand"
    assert validation.json()["contract"]["toolDirectoryEntries"] == 5
    with ZipFile(BytesIO(bundle.content)) as archive:
        directory = ToolDirectorySnapshot.model_validate_json(archive.read("tool-directory.json"))
    assert directory.exposure_mode == "on_demand"
    assert directory.content_hash == directory.digest()
    assert {entry.name for entry in directory.entries if entry.source == "mcp"} == {
        "mcp__tavily__tavily_search",
        "mcp__tavily__tavily_extract",
    }


@pytest.mark.asyncio
async def test_deployment_api_promotes_and_environment_sessions_pin_snapshot() -> None:
    application, _container = app_and_container(auto_execute=True)
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "release-manager",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/studio/drafts",
            headers=headers,
            json=draft_request("deployed-agent"),
        )
        draft_id = created.json()["draftId"]
        published = await client.post(f"/v1/studio/drafts/{draft_id}/publish", headers=headers)
        promoted = await client.post(
            "/v1/studio/deployments/promote",
            headers=headers,
            json={
                "agentName": "deployed-agent",
                "agentVersion": published.json()["version"],
                "environment": "production",
                "expectedEnvironmentRevision": 0,
                "canaryPercent": 100,
                "imageDigest": "sha256:" + "a" * 64,
                "executionProfile": "isolated-default",
                "config": {"LOG_LEVEL": "info"},
                "idempotencyKey": "api-first-release",
            },
        )
        deployment_id = promoted.json()["deployment"]["deploymentId"]
        deployment = await client.get(f"/v1/studio/deployments/{deployment_id}", headers=headers)
        environments = await client.get(
            "/v1/studio/agents/deployed-agent/environments", headers=headers
        )
        production = next(item for item in environments.json() if item["name"] == "production")
        policy = {
            **production["resourcePolicy"],
            "quota": {
                "maxRunBudgetUsd": 0.75,
                "maxModelTokens": 120_000,
                "maxArtifactBytes": 2_048,
            },
        }
        policy_updated = await client.put(
            "/v1/studio/agents/deployed-agent/environments/production/policy",
            headers=headers,
            json={
                "expectedEnvironmentRevision": production["revision"],
                "policy": policy,
            },
        )
        session = await client.post(
            "/v1/sessions",
            headers=headers,
            json={"agent_name": "deployed-agent", "environment": "production"},
        )

    assert promoted.status_code == 202
    assert deployment.json()["deployment"]["status"] == "succeeded"
    assert production["revision"] == 1
    assert production["routes"][0]["weight"] == 100
    assert policy_updated.status_code == 200
    assert policy_updated.json()["revision"] == 2
    assert policy_updated.json()["policyRevision"] == 2
    assert policy_updated.json()["policyHash"] != production["policyHash"]
    assert session.status_code == 201
    assert session.json()["agent_version"] == published.json()["version"]
    assert session.json()["deployment_snapshot_id"] == production["healthySnapshotId"]
    assert session.json()["environment_snapshot"]["policyRevision"] == 2
    assert (
        session.json()["environment_snapshot"]["resourcePolicy"]["quota"]["maxRunBudgetUsd"] == 0.75
    )


@pytest.mark.asyncio
async def test_webhook_trigger_is_secret_scoped_idempotent_and_disableable() -> None:
    application, _container = app_and_container(auto_execute=True)
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "release-manager",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/studio/drafts",
            headers=headers,
            json=draft_request("webhook-agent"),
        )
        draft_id = created.json()["draftId"]
        published = await client.post(
            f"/v1/studio/drafts/{draft_id}/publish",
            headers=headers,
        )
        promoted = await client.post(
            "/v1/studio/deployments/promote",
            headers=headers,
            json={
                "agentName": "webhook-agent",
                "agentVersion": published.json()["version"],
                "environment": "production",
                "expectedEnvironmentRevision": 0,
                "canaryPercent": 100,
                "imageDigest": "sha256:" + "b" * 64,
                "executionProfile": "isolated-default",
                "config": {},
                "idempotencyKey": "webhook-agent-release",
            },
        )
        trigger_created = await client.post(
            "/v1/studio/agents/webhook-agent/triggers",
            headers=headers,
            json={"name": "外部工单入口", "environment": "production"},
        )
        trigger = trigger_created.json()["trigger"]
        secret = trigger_created.json()["secret"]
        trigger_id = trigger["triggerId"]
        invocation_headers = {
            "Authorization": f"Bearer {secret}",
            "Idempotency-Key": "external-ticket-42",
        }
        first = await client.post(
            f"/webhooks/agent-triggers/{trigger_id}",
            headers=invocation_headers,
            json={"prompt": "分析工单 42"},
        )
        retry = await client.post(
            f"/webhooks/agent-triggers/{trigger_id}",
            headers=invocation_headers,
            json={"prompt": "分析工单 42"},
        )
        conflict = await client.post(
            f"/webhooks/agent-triggers/{trigger_id}",
            headers=invocation_headers,
            json={"prompt": "这是另一个请求"},
        )
        status_response = await client.get(
            f"/webhooks/agent-triggers/{trigger_id}/runs/{first.json()['runId']}",
            headers={"Authorization": f"Bearer {secret}"},
        )
        invalid = await client.post(
            f"/webhooks/agent-triggers/{trigger_id}",
            headers={
                "Authorization": "Bearer invalid-secret",
                "Idempotency-Key": "external-ticket-43",
            },
            json={"prompt": "不应运行"},
        )
        listed = await client.get(
            "/v1/studio/agents/webhook-agent/triggers",
            headers=headers,
        )
        rotated = await client.post(
            f"/v1/studio/triggers/{trigger_id}/rotate-secret",
            headers=headers,
            json={"expectedRevision": listed.json()[0]["revision"]},
        )
        rotated_secret = rotated.json()["secret"]
        old_secret = await client.post(
            f"/webhooks/agent-triggers/{trigger_id}",
            headers={
                "Authorization": f"Bearer {secret}",
                "Idempotency-Key": "external-ticket-44",
            },
            json={"prompt": "旧密钥不应运行"},
        )
        disabled = await client.put(
            f"/v1/studio/triggers/{trigger_id}",
            headers=headers,
            json={
                "expectedRevision": rotated.json()["trigger"]["revision"],
                "name": "外部工单入口",
                "enabled": False,
            },
        )
        disabled_invoke = await client.post(
            f"/webhooks/agent-triggers/{trigger_id}",
            headers={
                "Authorization": f"Bearer {rotated_secret}",
                "Idempotency-Key": "external-ticket-45",
            },
            json={"prompt": "禁用后不应运行"},
        )

    assert promoted.status_code == 202, promoted.text
    assert trigger_created.status_code == 201, trigger_created.text
    assert len(secret) >= 32
    assert "secretDigest" not in trigger
    assert first.status_code == 202, first.text
    assert first.json()["runId"] == retry.json()["runId"]
    assert first.json()["sessionId"] == retry.json()["sessionId"]
    assert first.json()["deploymentSnapshotId"] == promoted.json()["target"]["snapshotId"]
    assert conflict.status_code == 409
    assert status_response.status_code == 200
    assert status_response.json()["input"]["trigger_id"] == trigger_id
    assert invalid.status_code == 401
    assert len(listed.json()) == 1
    assert "secret" not in listed.json()[0]
    assert "secretDigest" not in listed.json()[0]
    assert rotated.status_code == 200
    assert rotated_secret != secret
    assert old_secret.status_code == 401
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled_invoke.status_code == 401


@pytest.mark.asyncio
async def test_a2a_chatops_schedule_and_platform_mcp_use_existing_control_plane() -> None:
    application, container = app_and_container(auto_execute=True)
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "platform-admin",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/studio/drafts",
            headers=headers,
            json=draft_request("interop-agent"),
        )
        published = await client.post(
            f"/v1/studio/drafts/{created.json()['draftId']}/publish",
            headers=headers,
        )
        promoted = await client.post(
            "/v1/studio/deployments/promote",
            headers=headers,
            json={
                "agentName": "interop-agent",
                "agentVersion": published.json()["version"],
                "environment": "production",
                "expectedEnvironmentRevision": 0,
                "canaryPercent": 100,
                "imageDigest": "sha256:" + "c" * 64,
                "executionProfile": "isolated-default",
                "config": {},
                "idempotencyKey": "interop-release",
            },
        )
        a2a_created = await client.post(
            "/v1/studio/agents/interop-agent/triggers",
            headers=headers,
            json={
                "name": "A2A",
                "environment": "production",
                "kind": "a2a",
            },
        )
        a2a = a2a_created.json()
        trigger_id = a2a["trigger"]["triggerId"]
        secret = a2a["secret"]
        card = await client.get(f"/a2a/agent-triggers/{trigger_id}/agent-card.json")
        a2a_headers = {
            "Authorization": f"Bearer {secret}",
            "A2A-Version": "1.0",
        }
        sent = await client.post(
            f"/a2a/agent-triggers/{trigger_id}/message:send",
            headers=a2a_headers,
            json={
                "message": {
                    "messageId": "a2a-message-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "执行互操作任务"}],
                }
            },
        )
        assert sent.status_code == 200, sent.text
        task_id = sent.json()["task"]["id"]
        task = await client.get(
            f"/a2a/agent-triggers/{trigger_id}/tasks/{task_id}",
            headers=a2a_headers,
        )
        cancelled = await client.post(
            f"/a2a/agent-triggers/{trigger_id}/tasks/{task_id}:cancel",
            headers=a2a_headers,
        )
        chatops_created = await client.post(
            "/v1/studio/agents/interop-agent/triggers",
            headers=headers,
            json={
                "name": "ChatOps",
                "environment": "production",
                "kind": "chatops",
                "chatops": {
                    "provider": "generic",
                    "allowedChannelIds": ["ops"],
                },
            },
        )
        chatops_id = chatops_created.json()["trigger"]["triggerId"]
        chatops = await client.post(
            f"/chatops/agent-triggers/{chatops_id}",
            headers={"Authorization": f"Bearer {chatops_created.json()['secret']}"},
            json={
                "messageId": "chat-message-1",
                "channelId": "ops",
                "actorId": "operator",
                "text": "执行 ChatOps 任务",
            },
        )
        schedule = await client.post(
            "/v1/studio/agents/interop-agent/triggers",
            headers=headers,
            json={
                "name": "Hourly",
                "environment": "production",
                "kind": "schedule",
                "schedule": {
                    "intervalSeconds": 3600,
                    "timezone": "Asia/Shanghai",
                    "prompt": "生成小时报告",
                },
            },
        )
        mcp_access = await client.post(
            "/v1/studio/platform-mcp/access",
            headers=headers,
        )

    schedule_id = schedule.json()["trigger"]["triggerId"]
    trigger_repository = cast(Any, container.triggers)._repository
    stored_schedule = await trigger_repository.get("tenant-a", schedule_id)
    due_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await trigger_repository.advance_schedule(
        schedule_id,
        expected_next_fire_at=stored_schedule.next_fire_at,
        next_fire_at=due_at,
    )
    dispatch_counts = await asyncio.gather(
        container.triggers.dispatch_due(),
        container.triggers.dispatch_due(),
    )
    schedule_key = f"schedule:{due_at.isoformat()}"
    schedule_digest = hashlib.sha256(f"{schedule_id}:{schedule_key}".encode()).hexdigest()
    schedule_session_id = f"trigger_session_{schedule_digest[:32]}"
    schedule_runs = await container.runs.list_for_sessions("tenant-a", [schedule_session_id])

    assert promoted.status_code == 202
    assert card.status_code == 200
    assert card.json()["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    assert card.json()["capabilities"]["streaming"] is True
    assert sent.status_code == 200
    assert task.json()["task"]["id"] == task_id
    assert cancelled.json()["task"]["status"]["state"] in {
        "TASK_STATE_WORKING",
        "TASK_STATE_COMPLETED",
    }
    assert chatops.status_code == 202
    assert chatops.json()["runId"]
    assert schedule.status_code == 201
    assert schedule.json()["trigger"]["nextFireAt"]
    assert sorted(dispatch_counts) == [0, 1]
    assert len(schedule_runs) == 1
    assert mcp_access.status_code == 200
    assert mcp_access.json()["mutations_enabled"] is False
    assert mcp_access.json()["token"]


@pytest.mark.asyncio
async def test_eval_control_plane_runs_cases_persists_reports_and_exposes_gate() -> None:
    application, container = app_and_container()
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "evaluator-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/studio/drafts",
            headers=headers,
            json=draft_request("evaluated-agent"),
        )
        draft_id = created.json()["draftId"]
        dataset = await client.post(
            "/v1/studio/eval-datasets",
            headers=headers,
            json={
                "draftId": draft_id,
                "expectedRevision": 1,
                "name": "发布必测集",
                "required": True,
            },
        )
        published = await client.post(
            f"/v1/studio/drafts/{draft_id}/publish",
            headers=headers,
            json={"expectedRevision": 1},
        )
        started = await client.post(
            "/v1/studio/eval-runs",
            headers=headers,
            json={
                "datasetId": dataset.json()["datasetId"],
                "datasetVersion": dataset.json()["version"],
                "agentName": "evaluated-agent",
                "agentVersion": published.json()["version"],
                "idempotencyKey": "evaluated-agent-release-1",
            },
        )
        eval_run_id = started.json()["run"]["evalRunId"]
        await drain_eval(container, eval_run_id)
        finished = await client.get(f"/v1/studio/eval-runs/{eval_run_id}", headers=headers)
        listed = await client.get("/v1/studio/eval-runs", headers=headers)
        gate = await client.get(
            "/v1/studio/evaluation-gates/evaluated-agent/versions/0.1.0",
            headers=headers,
        )
        artifacts = finished.json()["run"]["artifacts"]
        report = await client.get(
            f"/v1/studio/eval-runs/{eval_run_id}/artifacts/{artifacts[0]['artifactId']}",
            headers=headers,
        )

    assert dataset.status_code == 201, dataset.text
    assert dataset.json()["version"] == 1
    assert len(dataset.json()["cases"]) == 3
    assert started.status_code == 202, started.text
    assert finished.status_code == 200
    assert finished.json()["run"]["status"] == EvalRunStatus.PASSED
    assert finished.json()["passedCases"] == 3
    assert len({item["sessionId"] for item in finished.json()["cases"]}) == 3
    assert listed.json()[0]["run"]["evalRunId"] == eval_run_id
    assert gate.json() == {
        "agentName": "evaluated-agent",
        "agentVersion": "0.1.0",
        "passed": True,
        "requiredDatasets": 1,
        "passedDatasets": 1,
        "missingDatasetIds": [],
    }
    assert {item["name"] for item in artifacts} == {"report.json", "junit.xml"}
    assert report.status_code == 200
    assert report.headers["content-disposition"] == 'attachment; filename="report.json"'
    assert report.json()["passed"] is True


@pytest.mark.asyncio
async def test_memory_auto_execute_drives_eval_and_child_run_queues() -> None:
    application, container = app_and_container(auto_execute=True)
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "evaluator-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/studio/drafts",
            headers=headers,
            json=draft_request("auto-eval-agent"),
        )
        dataset = await client.post(
            "/v1/studio/eval-datasets",
            headers=headers,
            json={
                "draftId": created.json()["draftId"],
                "expectedRevision": 1,
                "name": "自动评测集",
            },
        )
        await client.post(
            f"/v1/studio/drafts/{created.json()['draftId']}/publish",
            headers=headers,
            json={"expectedRevision": 1},
        )
        started = await client.post(
            "/v1/studio/eval-runs",
            headers=headers,
            json={
                "datasetId": dataset.json()["datasetId"],
                "datasetVersion": 1,
                "agentName": "auto-eval-agent",
                "agentVersion": "0.1.0",
                "idempotencyKey": "auto-eval-one",
            },
        )

    stored = await container.eval_run_repository.get("tenant-a", started.json()["run"]["evalRunId"])
    assert stored.status is EvalRunStatus.PASSED


@pytest.mark.asyncio
async def test_publish_is_idempotent_and_writes_secret_free_domain_audit() -> None:
    application, container = app_and_container()
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "owner-a",
    }
    prompt_sentinel = "PROMPT_BODY_MUST_NOT_ENTER_AUDIT"
    file_sentinel = "PRIVATE_SKILL_FILE_MUST_NOT_ENTER_AUDIT"
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post("/v1/studio/drafts", headers=headers, json=draft_request())
        spec = created.json()["spec"]
        spec["systemPrompt"] += f"\n{prompt_sentinel}\n"
        spec["skills"][0]["files"] = [{"path": "references/private.md", "content": file_sentinel}]
        replaced = await client.put(
            f"/v1/studio/drafts/{created.json()['draftId']}",
            headers=headers,
            json={"expectedRevision": 1, "spec": spec},
        )
        first = await client.post(
            f"/v1/studio/drafts/{created.json()['draftId']}/publish",
            headers=headers,
            json={"expectedRevision": 2},
        )
        repeated = await client.post(
            f"/v1/studio/drafts/{created.json()['draftId']}/publish",
            headers=headers,
            json={"expectedRevision": 3},
        )
        stored = await client.get(f"/v1/studio/drafts/{created.json()['draftId']}", headers=headers)

    assert replaced.status_code == 200
    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert stored.json()["revision"] == 3
    domain_audits = [
        entry
        for entry in await container.audit.list_for_tenant("tenant-a", limit=20)
        if entry.action == "studio.publish"
    ]
    assert len(domain_audits) == 2
    assert {entry.details["idempotent"] for entry in domain_audits} == {
        False,
        True,
    }
    audit_json = json.dumps([entry.model_dump(mode="json") for entry in domain_audits])
    assert prompt_sentinel not in audit_json
    assert file_sentinel not in audit_json
    assert "systemPrompt" not in audit_json
    assert "files" not in audit_json


@pytest.mark.asyncio
async def test_changed_content_reusing_version_is_rejected_and_audited() -> None:
    application, container = app_and_container()
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "owner-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post("/v1/studio/drafts", headers=headers, json=draft_request())
        draft_id = created.json()["draftId"]
        first = await client.post(
            f"/v1/studio/drafts/{draft_id}/publish",
            headers=headers,
            json={"expectedRevision": 1},
        )
        changed_spec = (await client.get(f"/v1/studio/drafts/{draft_id}", headers=headers)).json()[
            "spec"
        ]
        changed_spec["description"] = "版本号未变化，但内容已经变化。"
        changed = await client.put(
            f"/v1/studio/drafts/{draft_id}",
            headers=headers,
            json={"expectedRevision": 2, "spec": changed_spec},
        )
        conflicting = await client.post(
            f"/v1/studio/drafts/{draft_id}/publish",
            headers=headers,
            json={"expectedRevision": 3},
        )

    assert first.status_code == 200
    assert changed.status_code == 200
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "version_conflict"
    audits = await container.audit.list_for_tenant("tenant-a", limit=20)
    denied = next(
        entry for entry in audits if entry.action == "studio.publish" and entry.outcome == "denied"
    )
    assert denied.details["error_code"] == "version_conflict"
    assert set(denied.details) == {
        "name",
        "version",
        "draft_revision",
        "error_code",
    }


@pytest.mark.asyncio
async def test_unpublished_subagent_blocks_validation_and_publish_api() -> None:
    application = app()
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "owner-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/studio/drafts",
            headers=headers,
            json={**draft_request("lead-agent"), "template": "orchestrator"},
        )
        draft_id = created.json()["draftId"]
        validation = await client.post(f"/v1/studio/drafts/{draft_id}/validate", headers=headers)
        published = await client.post(
            f"/v1/studio/drafts/{draft_id}/publish",
            headers=headers,
            json={"expectedRevision": 1},
        )

    assert validation.status_code == 200
    assert validation.json()["ready"] is False
    assert {issue["code"] for issue in validation.json()["issues"]} >= {"subagent_not_published"}
    assert published.status_code == 422
    assert published.json()["error"]["code"] == "draft_not_ready"
    assert {issue["code"] for issue in published.json()["error"]["issues"]} >= {
        "subagent_not_published"
    }


@pytest.mark.asyncio
async def test_preview_api_is_idempotent_stale_cancellable_and_never_publishes() -> None:
    application, container = app_and_container(auto_execute=True)
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "previewer-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/studio/drafts", headers=headers, json=draft_request("preview-agent")
        )
        draft_id = created.json()["draftId"]
        preview_request = {
            "draftId": draft_id,
            "expectedRevision": 1,
            "idempotencyKey": "preview-agent-r1",
            "ttlSeconds": 600,
        }
        first = await client.post("/v1/studio/previews", headers=headers, json=preview_request)
        repeated = await client.post("/v1/studio/previews", headers=headers, json=preview_request)
        listed = await client.get("/v1/studio/previews", headers=headers)
        current = await client.get(
            f"/v1/studio/previews/{first.json()['previewId']}", headers=headers
        )
        preflight_events = await client.get(
            f"/v1/studio/previews/{first.json()['previewId']}/events",
            headers=headers,
        )

        changed_spec = created.json()["spec"]
        changed_spec["description"] = "Draft changed after Preview creation."
        changed = await client.put(
            f"/v1/studio/drafts/{draft_id}",
            headers=headers,
            json={"expectedRevision": 1, "spec": changed_spec},
        )
        stale = await client.get(
            f"/v1/studio/previews/{first.json()['previewId']}", headers=headers
        )
        cancelling = await client.post(
            f"/v1/studio/previews/{first.json()['previewId']}/cancel",
            headers=headers,
        )
        cancelled = await client.get(
            f"/v1/studio/previews/{first.json()['previewId']}", headers=headers
        )

    assert first.status_code == 202
    assert first.json()["identityKind"] == "test"
    assert first.json()["environment"] == "preview"
    assert repeated.status_code == 202
    assert repeated.json()["previewId"] == first.json()["previewId"]
    assert len(listed.json()) == 1
    assert current.json()["status"] == "ready"
    assert current.json()["preflightResult"]["schemaVersion"] == "harness.preflight/v1"
    assert current.json()["preflightResult"]["status"] == "passed"
    assert {check["stage"] for check in current.json()["preflightResult"]["checks"]} == {
        "bundle",
        "sandbox_provision",
        "sandbox_prepare",
        "model",
        "mcp",
        "approval",
        "workspace_artifact",
        "cleanup",
    }
    assert preflight_events.status_code == 200
    assert len(preflight_events.json()) == 16
    assert changed.status_code == 200
    assert stale.json()["stale"] is True
    assert stale.json()["staleReason"] == "draft_revision_changed"
    assert cancelling.json()["status"] == "cancelling"
    assert cancelled.json()["status"] == "cancelled"
    registry = cast(InMemoryAgentRegistry, vars(container.agents)["_registry"])
    with pytest.raises(NotFoundError):
        await registry.get("tenant-a", "preview-agent", "0.1.0")


@pytest.mark.asyncio
async def test_jwt_identity_ignores_spoofed_tenant_and_user_headers() -> None:
    async with AsyncClient(transport=ASGITransport(app=app()), base_url="http://test") as client:
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
    async with AsyncClient(transport=ASGITransport(app=app()), base_url="http://test") as client:
        await register(client, "owner@example.com")
        member = await register(client, "member@example.com")
        headers = {"Authorization": f"Bearer {member['access_token']}"}
        created = await client.post("/v1/studio/drafts", headers=headers, json=draft_request())
        draft_id = created.json()["draftId"]
        validation = await client.post(f"/v1/studio/drafts/{draft_id}/validate", headers=headers)
        published = await client.post(f"/v1/studio/drafts/{draft_id}/publish", headers=headers)

    assert member["membership"]["role"] == "member"
    assert created.status_code == 201
    assert validation.status_code == 200
    assert published.status_code == 403
    assert published.json()["error"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_quota_usage_is_readable_but_only_admin_roles_can_change_policy() -> None:
    application, container = app_and_container()
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        owner = await register(client, "quota-owner@example.com")
        member = await register(client, "quota-member@example.com")
        viewer = await register(client, "quota-viewer@example.com")
        repository = cast(InMemoryAuthRepository, vars(container.auth)["_repository"])
        viewer_membership = Membership(
            tenant_id=viewer["membership"]["tenant_id"],
            user_id=viewer["user"]["user_id"],
            role="viewer",
            created_at=repository.memberships[
                (viewer["membership"]["tenant_id"], viewer["user"]["user_id"])
            ].created_at,
        )
        repository.memberships[(viewer_membership.tenant_id, viewer_membership.user_id)] = (
            viewer_membership
        )
        viewer_login = await client.post(
            "/v1/auth/login",
            json={"email": "quota-viewer@example.com", "password": "SecurePass123"},
        )
        owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
        member_headers = {"Authorization": f"Bearer {member['access_token']}"}
        viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}

        initial = await client.get("/v1/studio/quotas", headers=viewer_headers)
        member_write = await client.put(
            "/v1/studio/quotas/tenant-default",
            headers=member_headers,
            json={"expectedRevision": 0, "scope": {}, "limits": {"concurrent_runs": 3}},
        )
        viewer_write = await client.put(
            "/v1/studio/quotas/tenant-default",
            headers=viewer_headers,
            json={"expectedRevision": 0, "scope": {}, "limits": {"concurrent_runs": 3}},
        )
        changed = await client.put(
            "/v1/studio/quotas/tenant-default",
            headers=owner_headers,
            json={"expectedRevision": 0, "scope": {}, "limits": {"concurrent_runs": 3}},
        )
        current = await client.get("/v1/studio/quotas", headers=member_headers)

    assert initial.status_code == 200
    assert initial.json()["policies"][0]["revision"] == 0
    assert member_write.status_code == 403
    assert viewer_write.status_code == 403
    assert changed.status_code == 200
    assert changed.json()["revision"] == 1
    assert current.status_code == 200
    assert current.json()["policies"][0]["limits"]["concurrent_runs"] == 3
    audits = await container.audit.list_for_tenant(owner["membership"]["tenant_id"], limit=20)
    assert any(
        entry.action == "quota.policy.replace"
        and entry.resource_id == "tenant-default"
        and entry.user_id == owner["user"]["user_id"]
        for entry in audits
    )


@pytest.mark.asyncio
async def test_preview_quota_rejection_does_not_create_a_half_preview() -> None:
    application, container = app_and_container()
    await container.quotas.replace_policy(
        tenant_id="tenant-a",
        user_id="owner-a",
        policy_id="tenant-default",
        request=ReplaceQuotaPolicyRequest(
            expectedRevision=0,
            limits={QuotaResource.ACTIVE_PREVIEWS: 1},
        ),
    )
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "owner-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        draft = await client.post(
            "/v1/studio/drafts", headers=headers, json=draft_request("preview-quota")
        )
        first = await client.post(
            "/v1/studio/previews",
            headers=headers,
            json={
                "draftId": draft.json()["draftId"],
                "expectedRevision": 1,
                "idempotencyKey": "preview-quota-one",
                "ttlSeconds": 600,
            },
        )
        rejected = await client.post(
            "/v1/studio/previews",
            headers=headers,
            json={
                "draftId": draft.json()["draftId"],
                "expectedRevision": 1,
                "idempotencyKey": "preview-quota-two",
                "ttlSeconds": 600,
            },
        )
        listed = await client.get("/v1/studio/previews", headers=headers)

    assert first.status_code == 202
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "quota_exceeded"
    assert "active_previews" in rejected.json()["error"]["message"]
    assert [item["previewId"] for item in listed.json()] == [first.json()["previewId"]]


@pytest.mark.asyncio
async def test_catalog_is_admin_managed_secret_free_and_drives_live_validation() -> None:
    owner_headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "owner-a",
    }
    async with AsyncClient(transport=ASGITransport(app=app()), base_url="http://test") as client:
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
        member_catalog = await client.get("/v1/studio/catalog", headers=member_headers)

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
    assert {issue["code"] for issue in validation.json()["issues"]} >= {"model_route_disabled"}
    assert current.status_code == 200
    assert current.json()["revision"] == 2
    assert member_catalog.status_code == 200
    assert member_catalog.json()["tenantId"] == member["membership"]["tenant_id"]


@pytest.mark.asyncio
async def test_catalog_admin_can_discover_mcp_tools_but_member_cannot() -> None:
    class Connector:
        async def discover(
            self,
            endpoint_url: str,
            *,
            headers: Mapping[str, str],
            timeout_seconds: float,
        ) -> DiscoveredServer:
            assert endpoint_url == "https://mcp.example.com/mcp"
            assert headers == {}
            assert timeout_seconds == 12
            return DiscoveredServer(
                title="Company MCP",
                version="1.0.0",
                tools=(
                    ("search", "Search", "Search documents"),
                    ("open", "Open", "Open a document"),
                ),
            )

    async def resolve_public(_host: str, _port: int) -> tuple[str, ...]:
        return ("1.1.1.1",)

    application, container = app_and_container()
    object.__setattr__(
        container,
        "mcp_discovery",
        McpDiscoveryService(
            connector=Connector(),
            host_resolver=resolve_public,
        ),
    )
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        owner = await register(client, "mcp-owner@example.com")
        member = await register(client, "mcp-member@example.com")
        body = {
            "reference": "company-search",
            "serverName": "company",
            "endpointUrl": "https://mcp.example.com/mcp",
            "networkAccess": "external",
            "authMode": "none",
            "authKey": "authorization",
        }
        discovered = await client.post(
            "/v1/studio/mcp/discover",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
            json=body,
        )
        rejected = await client.post(
            "/v1/studio/mcp/discover",
            headers={"Authorization": f"Bearer {member['access_token']}"},
            json=body,
        )

    assert discovered.status_code == 200
    assert discovered.json()["transport"] == "http"
    assert [tool["canonicalName"] for tool in discovered.json()["tools"]] == [
        "mcp__company__search",
        "mcp__company__open",
    ]
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "permission_denied"


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
        stored_before = await registry.get("tenant-a", "policy-researcher", "0.1.0")
        disabled = await client.delete(
            "/v1/studio/catalog/modelRoute/new-api-default",
            headers=owner_headers,
            params={"expected_revision": 1},
        )
        stored_after = await registry.get("tenant-a", "policy-researcher", "0.1.0")

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
    async with AsyncClient(transport=ASGITransport(app=app()), base_url="http://test") as client:
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
    async with AsyncClient(transport=ASGITransport(app=app()), base_url="http://test") as client:
        created = await client.post("/v1/studio/drafts", headers=tenant_a, json=draft_request())
        draft_id = created.json()["draftId"]
        hidden = await client.get(f"/v1/studio/drafts/{draft_id}", headers=tenant_b)

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
        invalid_bundle = await client.get(f"/v1/studio/drafts/{draft_id}/bundle", headers=tenant_a)

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
        "/v1/studio/previews",
        "/v1/studio/previews/{preview_id}",
        "/v1/studio/previews/{preview_id}/events",
        "/v1/studio/previews/{preview_id}/cancel",
    }

    assert expected <= set(schema["paths"])
    assert schema["paths"]["/v1/studio/drafts"]["post"]["responses"].keys() >= {
        "201",
        "422",
    }
