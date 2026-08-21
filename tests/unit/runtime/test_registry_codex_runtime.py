from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr

from harness.adapters.memory import InMemoryAgentRegistry
from harness.core.manifest import load_manifest
from harness.core.models import AgentVersion, AgentVersionStatus, Run, RunStatus, Session
from harness.runtime.base import RuntimeContext
from harness.runtime.codex_app_server import CodexAppServerOptions
from harness.runtime.codex_protocol import CodexMessage, CodexMessageKind
from harness.runtime.codex_runtime import CodexProcess, CodexRpcConnection
from harness.runtime.registry_codex_runtime import RegistryCodexRuntime
from harness.studio.catalog_repository import InMemoryCapabilityCatalogRepository
from harness.studio.catalog_service import CapabilityCatalogService
from harness.studio.mcp_credential_store import (
    InMemoryMcpCredentialRepository,
    McpCredentialCipher,
    McpCredentialService,
)
from harness.studio.model_configuration import (
    BindAgentModelRequest,
    ConfigureModelRequest,
    ModelConfigurationService,
)
from harness.studio.repositories import InMemoryAgentDraftRepository


class _Client:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    async def request(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> object:
        del timeout_seconds
        values = dict(params or {})
        self.requests.append((method, values))
        if method == "thread/start":
            return {"thread": {"id": "thread-control-plane"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-control-plane"}}
        raise AssertionError(f"unexpected request: {method}")

    async def respond(self, request_id: int | str, result: object) -> None:
        del request_id, result

    async def respond_error(
        self,
        request_id: int | str,
        *,
        code: int,
        message: str,
    ) -> None:
        del request_id, code, message

    async def inbound(self) -> AsyncIterator[CodexMessage]:
        yield CodexMessage(
            CodexMessageKind.NOTIFICATION,
            {
                "method": "turn/completed",
                "params": {"turn": {"status": "completed"}},
            },
        )


class _Process:
    def __init__(self, client: _Client) -> None:
        self.client: CodexRpcConnection | None = cast(CodexRpcConnection, client)

    async def start(self) -> Mapping[str, object]:
        return {}

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_control_plane_model_becomes_secret_safe_codex_provider(
    tmp_path: Path,
) -> None:
    snapshot = load_manifest("agents/helper-agent/agent.yaml")
    manifest = snapshot.manifest.model_copy(
        update={
            "spec": snapshot.manifest.spec.model_copy(
                update={"runtime": "codex-app-server"}
            )
        }
    )
    snapshot = snapshot.model_copy(update={"manifest": manifest})
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            owner_user_id="user-a",
            name="helper-agent",
            version="1.0.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    catalogs = CapabilityCatalogService(
        InMemoryCapabilityCatalogRepository(),
        InMemoryAgentDraftRepository(),
    )
    model_configurations = ModelConfigurationService(
        catalogs,
        McpCredentialService(
            InMemoryMcpCredentialRepository(),
            McpCredentialCipher(SecretStr("test-model-encryption")),
        ),
        environment="test",
    )
    configured = await model_configurations.configure(
        "tenant-a",
        "admin-a",
        "codex-responses",
        ConfigureModelRequest(
            expectedRevision=1,
            label="Codex Responses",
            modelType="chat",
            provider="Example Responses",
            model="gpt-control-plane",
            baseUrl="https://models.example.test/v1",
            apiFormat="openai_compatible",
            authScheme="bearer",
            apiKey=SecretStr("control-plane-secret"),
        ),
    )
    await model_configurations.bind_agent(
        "tenant-a",
        "admin-a",
        "helper-agent",
        BindAgentModelRequest(
            expectedRevision=configured.revision,
            routeId="codex-responses",
        ),
    )
    client = _Client()
    options_seen: list[CodexAppServerOptions] = []

    def process_factory(options: CodexAppServerOptions) -> CodexProcess:
        options_seen.append(options)
        return cast(CodexProcess, _Process(client))

    runtime = RegistryCodexRuntime(
        registry=registry,
        codex_path=tmp_path / "codex",
        model_configurations=model_configurations,
        environment={"PATH": "/usr/bin"},
        process_factory=process_factory,
    )
    now = datetime.now(UTC)
    context = RuntimeContext(
        run=Run(
            run_id="run-codex",
            session_id="session-codex",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="codex",
            created_at=now,
            updated_at=now,
            input={"prompt": "respond"},
        ),
        session=Session(
            session_id="session-codex",
            tenant_id="tenant-a",
            user_id="developer",
            agent_owner_user_id="user-a",
            agent_name="helper-agent",
            agent_version="1.0.0",
            runtime_type="codex-app-server",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    options = options_seen[0]
    assert options.environment is not None
    assert options.environment["HARNESS_CODEX_PROVIDER_API_KEY"] == (
        "control-plane-secret"
    )
    assert options.environment["PATH"] == "/usr/bin"
    assert any(
        override == 'model_provider="agent_studio"'
        for override in options.config_overrides
    )
    assert any(
        override
        == 'model_providers.agent_studio.base_url="https://models.example.test/v1"'
        for override in options.config_overrides
    )
    assert all("control-plane-secret" not in value for value in options.config_overrides)
    thread_start = client.requests[0][1]
    assert thread_start["model"] == "gpt-control-plane"
    assert thread_start["modelProvider"] == "agent_studio"
    selected = events[0]
    assert selected.payload["route_id"] == "codex-responses"
    assert selected.payload["provider"] == "new-api"
    assert "control-plane-secret" not in repr(events)
