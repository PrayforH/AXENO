from types import MappingProxyType
from typing import cast

import jwt
import pytest
from pydantic import SecretStr

from harness.core.models import ExecutionIdentity
from harness.memory_bank.workload import MemoryWorkloadTokenService, RemoteMemoryMcpProvider
from harness.runtime.tools import ResolvedTools


def identity() -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="agent-a",
        session_id="session-a",
        run_id="run-a",
        agent_name="agent-a",
        agent_version="1.0.0",
    )


def test_workload_token_round_trips_exact_execution_scope() -> None:
    tokens = MemoryWorkloadTokenService(SecretStr("x" * 32))

    assert tokens.verify(tokens.issue(identity())) == identity()


def test_workload_token_rejects_signed_token_with_incomplete_scope() -> None:
    tokens = MemoryWorkloadTokenService(SecretStr("x" * 32))
    incomplete = jwt.encode(
        {
            "iss": "claude-agent-harness",
            "aud": "harness-memory-bank",
            "exp": 4_102_444_800,
            "iat": 1_752_643_200,
            "purpose": "memory-proposal",
        },
        "x" * 32,
        algorithm="HS256",
    )

    with pytest.raises(jwt.MissingRequiredClaimError):
        tokens.verify(incomplete)


def test_remote_provider_injects_scoped_http_mcp_and_redacts_token() -> None:
    tokens = MemoryWorkloadTokenService(SecretStr("x" * 32))
    provider = RemoteMemoryMcpProvider("https://memory.example/mcp", tokens)
    empty = ResolvedTools(
        builtin_tools=(),
        mcp_servers=MappingProxyType({}),
        allowed_tools=(),
        mcp_smokes=MappingProxyType({}),
    )

    resolved = provider.attach(empty, identity())

    config = cast(dict[str, object], resolved.mcp_servers["harness-memory"])
    headers = cast(dict[str, str], config["headers"])
    token = headers["Authorization"].removeprefix("Bearer ")
    assert config["type"] == "http"
    assert config["url"] == "https://memory.example/mcp"
    assert tokens.verify(token) == identity()
    assert "mcp__harness-memory__propose_memory" in resolved.allowed_tools
    assert token in resolved.sensitive_values
