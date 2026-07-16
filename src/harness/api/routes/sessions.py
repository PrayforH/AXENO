from typing import Annotated

from fastapi import APIRouter, Depends, status

from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    get_container,
    require_identity,
)
from harness.api.schemas import CreateSessionRequest
from harness.core.models import Session
from harness.deployments.models import EnvironmentName

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Session:
    ensure_permission(identity, "tasks:write")
    return await container.sessions.create(
        identity.tenant_id,
        identity.user_id,
        body.agent_name,
        body.agent_version,
        environment=(EnvironmentName(body.environment) if body.environment else None),
    )
