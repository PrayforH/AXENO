from typing import Annotated

from fastapi import APIRouter, Depends, status

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
