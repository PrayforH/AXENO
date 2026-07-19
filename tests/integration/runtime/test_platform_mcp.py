from datetime import timedelta

import httpx
import pytest
from httpx import ASGITransport
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from harness.api.app import create_memory_app


@pytest.mark.asyncio
async def test_platform_mcp_is_server_scoped_and_read_only() -> None:
    app = create_memory_app()
    container = app.state.container
    token = container.platform_mcp_tokens.issue(
        "tenant-a", "admin-a", frozenset({"admin"})
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://platform",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            async with streamable_http_client(
                "http://platform/mcp/platform/mcp", http_client=client
            ) as (read_stream, write_stream, _session_id):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=5),
                ) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    usage = await session.call_tool("get_quota_usage", {})

    assert {tool.name for tool in tools.tools} == {
        "get_quota_usage",
        "list_agents",
        "list_environments",
        "list_governed_policies",
    }
    assert all(
        not tool.name.startswith(("create_", "update_", "delete_", "publish_"))
        for tool in tools.tools
    )
    assert usage.isError is not True


@pytest.mark.asyncio
async def test_platform_mcp_rejects_non_admin_and_invalid_tokens() -> None:
    app = create_memory_app()
    container = app.state.container
    viewer = container.platform_mcp_tokens.issue(
        "tenant-a", "viewer-a", frozenset({"viewer"})
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://platform"
        ) as client:
            invalid = await client.post(
                "/mcp/platform/mcp",
                json={},
                headers={"Authorization": "Bearer invalid"},
            )
            unauthorized_role = await client.post(
                "/mcp/platform/mcp",
                json={},
                headers={"Authorization": f"Bearer {viewer}"},
            )

    assert invalid.status_code == 401
    assert unauthorized_role.status_code == 401
