from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from harness.api.dependencies import ApiContainer, Identity, get_container, require_identity
from harness.api.schemas import PublishAgentRequest
from harness.core.models import AgentVersion

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentVersion, status_code=status.HTTP_201_CREATED)
async def publish_agent(
    body: PublishAgentRequest,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AgentVersion:
    return await container.agents.publish(identity.tenant_id, body.path)


@router.get("", response_model=list[AgentVersion])
async def list_agents(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentVersion]:
    return await container.agents.list_agents(
        identity.tenant_id, limit=limit, offset=offset
    )


@router.get("/{name}", response_model=list[AgentVersion])
async def get_agent_versions(
    name: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> list[AgentVersion]:
    return await container.agents.get_with_versions(identity.tenant_id, name)
