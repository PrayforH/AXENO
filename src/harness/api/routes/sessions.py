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
from harness.core.errors import ConflictError
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
    resolved_owner = body.agent_owner_user_id or identity.user_id
    team_ids: tuple[str, ...] = ()
    connection_mode = "caller_owned"
    if body.space_id is not None:
        if body.agent_version is None:
            raise ConflictError("shared Agents require an immutable agent_version")
        release = await container.team_spaces.require_agent_access(
            identity.tenant_id,
            identity.user_id,
            body.space_id,
            resolved_owner,
            body.agent_name,
            body.agent_version,
        )
        team_ids = (body.space_id,)
        connection_mode = release.connection_mode.value
    elif resolved_owner != identity.user_id:
        raise ConflictError("agent_owner_user_id requires a team space grant")
    return await container.sessions.create(
        identity.tenant_id,
        identity.user_id,
        body.agent_name,
        body.agent_version,
        environment=(EnvironmentName(body.environment) if body.environment else None),
        team_ids=team_ids,
        agent_owner_user_id=resolved_owner,
        connection_mode=connection_mode,
    )
