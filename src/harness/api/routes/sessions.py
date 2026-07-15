from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from harness.api.dependencies import ApiContainer, Identity, get_container, require_identity
from harness.api.schemas import CreateSessionRequest
from harness.core.models import Session

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Session:
    return await container.sessions.create(
        identity.tenant_id,
        identity.user_id,
        body.agent_name,
        body.agent_version,
    )


@router.get("", response_model=list[Session])
async def list_sessions(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Session]:
    return await container.sessions.list_by_user(
        identity.tenant_id,
        identity.user_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Session:
    return await container.sessions.get(identity.tenant_id, session_id)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> None:
    await container.sessions.delete(identity.tenant_id, session_id)
