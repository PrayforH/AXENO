"""Opt-in live smoke for Daytona, Anthropic-compatible model and reviewed MCP."""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from pydantic import SecretStr

from harness.config import Settings
from harness.core.models import ModelCompatibility
from harness.policy.profiles import default_policy_profiles
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.runtime.default_tools import (
    default_tool_resolver,
    server_secret_credential_provider,
)
from harness.sandbox.daytona import DaytonaSandboxProvider, SdkDaytonaClient
from harness.studio.catalog import default_capability_catalog
from harness.studio.compiler import AgentDraftCompiler
from harness.studio.models import (
    AgentTemplate,
    CreateAgentDraftRequest,
    ReplaceAgentDraftRequest,
)
from harness.studio.preflight import LivePreflightRunner
from harness.studio.preflight_models import PreflightResultStatus
from harness.studio.preflight_probes import (
    AnthropicSandboxModelProbe,
    StreamableHttpMcpProbe,
)
from harness.studio.preview_models import PreviewDeployment, PreviewStatus
from harness.studio.repositories import InMemoryAgentDraftRepository
from harness.studio.service import AgentStudioService


def _enabled() -> bool:
    return os.getenv("HARNESS_RUN_PREFLIGHT_LIVE_TESTS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@pytest.mark.asyncio
async def test_daytona_model_and_mcp_live_preflight() -> None:
    if not _enabled():
        pytest.skip("set HARNESS_RUN_PREFLIGHT_LIVE_TESTS=1 to run Daytona Preflight")
    settings = Settings()
    daytona_key = settings.daytona_api_key.get_secret_value()
    model_key = settings.new_api_key.get_secret_value()
    mcp_secrets = settings.mcp_server_secrets_json.get_secret_value()
    if not daytona_key or not settings.new_api_base_url or not settings.new_api_model:
        pytest.skip("Daytona and Anthropic-compatible model settings are required")
    if not model_key or mcp_secrets.strip() in {"", "{}"}:
        pytest.skip("Model and reviewed MCP credentials are required")

    now = datetime.now(UTC)
    catalog = default_capability_catalog()
    studio = AgentStudioService(
        InMemoryAgentDraftRepository(),
        AgentDraftCompiler(catalog),
        catalog,
        clock=lambda: now,
        id_generator=lambda: "draft-live-preflight",
    )
    draft = await studio.create(
        tenant_id="live-preflight",
        user_id="live-smoke",
        request=CreateAgentDraftRequest(
            name="live-preflight-agent",
            domain="live-preflight",
            displayName="Live Preflight Agent",
            description="Verify target model, Sandbox, MCP and Artifact boundaries.",
            template=AgentTemplate.ANALYST,
        ),
    )
    draft = await studio.replace(
        tenant_id="live-preflight",
        user_id="live-smoke",
        draft_id=draft.draft_id,
        request=ReplaceAgentDraftRequest(
            expectedRevision=1,
            spec=draft.spec.model_copy(
                update={"mcp_servers": ("tavily-readonly",)}
            ),
        ),
    )
    validation = await studio.validate("live-preflight", draft.draft_id)
    assert validation.ready
    assert validation.content_hash and validation.package_hash
    preview = PreviewDeployment(
        previewId="preview-live-smoke",
        tenantId="live-preflight",
        draftId=draft.draft_id,
        draftRevision=draft.revision,
        contentHash=validation.content_hash,
        packageHash=validation.package_hash,
        requestedBy="live-smoke",
        idempotencyKey="preview-live-smoke",
        status=PreviewStatus.PROVISIONING,
        createdAt=now,
        updatedAt=now,
        expiresAt=now + timedelta(minutes=10),
    )
    sandbox = DaytonaSandboxProvider(
        client=SdkDaytonaClient.from_config(
            api_key=daytona_key,
            api_url=settings.daytona_api_url or None,
            target=settings.daytona_target or None,
        ),
        snapshot=settings.daytona_snapshot or None,
        remote_workspace_root=settings.daytona_remote_workspace_root,
        cli_version=settings.daytona_claude_cli_version,
        cli_path=settings.daytona_claude_cli_path,
        delete_on_destroy=True,
    )
    gateway = CcSwitchClaudeConfig(
        base_url=settings.new_api_base_url,
        model=settings.new_api_model,
        provider="new-api",
        credential=SecretStr(model_key),
        compatibility=ModelCompatibility(settings.new_api_compatibility),
        capabilities=frozenset(
            part.strip()
            for part in settings.new_api_capabilities.split(",")
            if part.strip()
        ),
    )
    credentials = server_secret_credential_provider(
        references_json=settings.mcp_secret_references_json,
        secrets_json=mcp_secrets,
    )
    runner = LivePreflightRunner(
        studio=studio,
        sandbox=sandbox,
        model_probe=AnthropicSandboxModelProbe(gateway),
        mcp_probe=StreamableHttpMcpProbe(default_tool_resolver(credentials)),
        policies=default_policy_profiles(),
        timeout_seconds=settings.preflight_timeout_seconds,
    )

    async def active() -> bool:
        return False

    result = await runner.run(preview, cancelled=active)

    assert result.status is PreflightResultStatus.PASSED
    serialized = result.model_dump_json()
    assert daytona_key not in serialized
    assert model_key not in serialized
    secret_payload: object = json.loads(mcp_secrets)
    if isinstance(secret_payload, dict):
        for value in cast(dict[object, object], secret_payload).values():
            if isinstance(value, str) and value:
                assert value not in serialized
