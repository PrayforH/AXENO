import json
from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr

from harness.api.dependencies import build_memory_container
from harness.config import Settings
from harness.core.manifest import AgentManifest
from harness.core.models import ExecutionIdentity
from harness.runtime.cc_switch import CcSwitchConfigError
from harness.runtime.fake import FakeRuntime
from harness.runtime.registry_runtime import RegistryClaudeRuntime
from harness.runtime.tools import ToolResolver


def tavily_manifest() -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "apiVersion": "harness/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": "web-agent", "version": "1.0.0"},
            "spec": {
                "runtime": "claude-agent-sdk",
                "model": {"route": "default", "model": "gateway-model"},
                "prompt": {"system": "prompts/system.md"},
                "tools": [{"mcp": "tavily-readonly"}],
                "permissions": {"policy": "default"},
            },
        }
    )


def execution_identity() -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="web-agent",
        session_id="session-a",
        run_id="run-a",
        agent_name="web-agent",
        agent_version="1.0.0",
    )


def test_default_composition_uses_fake_runtime() -> None:
    container = build_memory_container(settings=Settings(runtime="fake"))

    assert isinstance(container.runtime, FakeRuntime)


def test_claude_sdk_composition_loads_cc_switch_runtime(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://gateway.example",
                    "ANTHROPIC_AUTH_TOKEN": "composition-secret",
                    "ANTHROPIC_MODEL": "composition-model",
                }
            }
        ),
        encoding="utf-8",
    )

    container = build_memory_container(
        settings=Settings(
            runtime="claude-sdk",
            cc_switch_settings_path=str(path),
        )
    )

    assert isinstance(container.runtime, RegistryClaudeRuntime)
    assert "composition-secret" not in repr(container)


@pytest.mark.asyncio
async def test_local_claude_composition_uses_server_owned_mcp_registry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://gateway.example",
                    "ANTHROPIC_AUTH_TOKEN": "composition-secret",
                    "ANTHROPIC_MODEL": "composition-model",
                }
            }
        ),
        encoding="utf-8",
    )
    container = build_memory_container(
        settings=Settings(
            runtime="claude-sdk",
            cc_switch_settings_path=str(path),
            mcp_secret_references_json=json.dumps(
                {"tavily-readonly": {"authorization": "TAVILY_AUTHORIZATION"}}
            ),
            mcp_server_secrets_json=SecretStr(
                json.dumps({"TAVILY_AUTHORIZATION": "Bearer local-key"})
            ),
        )
    )
    runtime = cast(RegistryClaudeRuntime, container.runtime)
    resolver = cast(ToolResolver, vars(runtime)["_tool_resolver"])

    resolved = await resolver.resolve(tavily_manifest(), execution_identity())

    assert resolved.mcp_servers["tavily"]["headers"] == {
        "Authorization": "Bearer local-key"
    }


def test_claude_sdk_composition_fails_instead_of_falling_back(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    with pytest.raises(CcSwitchConfigError, match="not found"):
        build_memory_container(
            settings=Settings(
                runtime="claude-sdk",
                cc_switch_settings_path=str(missing_path),
            )
        )


def test_daytona_composition_requires_explicit_credentials() -> None:
    with pytest.raises(ValueError, match="HARNESS_DAYTONA_API_KEY"):
        build_memory_container(
            settings=Settings(
                sandbox_provider="daytona", daytona_api_key=SecretStr("")
            )
        )
