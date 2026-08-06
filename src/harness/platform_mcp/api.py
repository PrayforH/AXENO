from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from harness.api.dependencies import Identity, ensure_permission, require_identity

router = APIRouter(prefix="/v1/studio/platform-mcp", tags=["platform-mcp"])


class PlatformMcpAccess(BaseModel):
    model_config = ConfigDict(frozen=True)
    url: str
    token: str
    expires_in_seconds: int = 300
    mutations_enabled: bool = False


@router.post("/access", response_model=PlatformMcpAccess)
async def issue_platform_mcp_access(
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
) -> PlatformMcpAccess:
    ensure_permission(identity, "studio:read")
    token = request.app.state.container.platform_mcp_tokens.issue(
        identity.tenant_id, identity.user_id, identity.roles
    )
    return PlatformMcpAccess(
        url=f"{str(request.base_url).rstrip('/')}/mcp/platform/mcp",
        token=token,
    )
