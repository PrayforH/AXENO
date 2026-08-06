from __future__ import annotations

from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import cast

import jwt
from mcp.server.fastmcp import FastMCP
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from harness.application.agents import AgentService
from harness.deployments.service import DeploymentService
from harness.governance.service import GovernanceService
from harness.quota.service import QuotaService

type PlatformIdentity = tuple[str, str, frozenset[str]]
_identity: ContextVar[PlatformIdentity | None] = ContextVar("platform_mcp_identity", default=None)


class PlatformMcpTokenService:
    def __init__(self, secret: SecretStr, *, ttl_seconds: int = 300) -> None:
        if len(secret.get_secret_value()) < 32:
            raise ValueError("platform MCP token secret must be at least 32 characters")
        self._secret = secret.get_secret_value()
        self._ttl = ttl_seconds

    def issue(self, tenant_id: str, user_id: str, roles: frozenset[str]) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "iss": "agent-studio",
                "aud": "harness-platform-mcp",
                "iat": now,
                "exp": now + timedelta(seconds=self._ttl),
                "tenant": tenant_id,
                "user": user_id,
                "roles": sorted(roles),
                "purpose": "platform-read",
            },
            self._secret,
            algorithm="HS256",
        )

    def verify(self, token: str) -> PlatformIdentity:
        payload = jwt.decode(
            token,
            self._secret,
            algorithms=["HS256"],
            audience="harness-platform-mcp",
            issuer="agent-studio",
            options={"require": ["exp", "iat", "tenant", "user", "roles", "purpose"]},
        )
        if payload.get("purpose") != "platform-read":
            raise jwt.InvalidTokenError("invalid platform MCP purpose")
        raw_roles: object = payload["roles"]
        if not isinstance(raw_roles, list):
            raise jwt.InvalidTokenError("invalid platform MCP roles")
        role_values = cast(list[object], raw_roles)
        return (
            str(payload["tenant"]),
            str(payload["user"]),
            frozenset(str(value) for value in role_values),
        )


class PlatformMcpAuthMiddleware:
    def __init__(self, app: ASGIApp, *, tokens: PlatformMcpTokenService) -> None:
        self._app = app
        self._tokens = tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        scheme, separator, credential = headers.get("authorization", "").partition(" ")
        try:
            if not separator or scheme.lower() != "bearer":
                raise jwt.InvalidTokenError
            identity = self._tokens.verify(credential)
            if not identity[2].intersection({"owner", "admin", "deployer"}):
                raise jwt.InvalidTokenError
        except jwt.PyJWTError:
            await JSONResponse(
                {"error": {"code": "platform_mcp_auth_required"}},
                status_code=401,
            )(scope, receive, send)
            return
        token = _identity.set(identity)
        try:
            await self._app(scope, receive, send)
        finally:
            _identity.reset(token)


def _tenant() -> str:
    identity = _identity.get()
    if identity is None:
        raise RuntimeError("platform MCP identity is unavailable")
    return identity[0]


def _user() -> str:
    identity = _identity.get()
    if identity is None:
        raise RuntimeError("platform MCP identity is unavailable")
    return identity[1]


def build_platform_mcp_app(
    *,
    agents: AgentService,
    deployments: DeploymentService,
    quotas: QuotaService,
    governance: GovernanceService,
    tokens: PlatformMcpTokenService,
) -> Starlette:
    server = FastMCP(
        "agent-studio-platform",
        instructions=(
            "Read-only Agent Studio control-plane facts. Tenant and role are always server-issued."
        ),
        host="0.0.0.0",
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @server.tool(name="list_agents", description="List immutable published Agents.")
    async def list_agents() -> dict[str, object]:
        values = await agents.list_published(_tenant(), _user())
        return {
            "agents": [
                {
                    "name": item.name,
                    "version": item.version,
                    "manifestHash": item.manifest_hash,
                    "createdAt": item.created_at.isoformat(),
                }
                for item in values
            ]
        }

    @server.tool(
        name="list_environments",
        description="List deployment environments for a published Agent.",
    )
    async def list_environments(agent_name: str) -> dict[str, object]:
        values = await deployments.list_environments(_tenant(), _user(), agent_name)
        return {"environments": [item.model_dump(mode="json", by_alias=True) for item in values]}

    @server.tool(
        name="get_quota_usage",
        description="Read scoped reservations, counters and active budget alerts.",
    )
    async def get_quota_usage() -> dict[str, object]:
        value = await quotas.usage(_tenant())
        return value.model_dump(mode="json", by_alias=True)

    @server.tool(
        name="list_governed_policies",
        description="List policy drafts and their published revisions.",
    )
    async def list_governed_policies() -> dict[str, object]:
        values = await governance.list_policies(_tenant())
        return {"policies": [item.model_dump(mode="json", by_alias=True) for item in values]}

    _ = (
        list_agents,
        list_environments,
        get_quota_usage,
        list_governed_policies,
    )

    app = server.streamable_http_app()
    app.add_middleware(PlatformMcpAuthMiddleware, tokens=tokens)
    return app
