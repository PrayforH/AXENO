from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from harness.agent_package import MAX_AGENT_BUNDLE_UPLOAD_BYTES
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
    if not container.agents.path_publication_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_path_publication_disabled",
                "message": "production accepts reproducible Agent bundles, not server-local paths",
            },
        )
    return await container.agents.publish(identity.tenant_id, body.path)


@router.post(
    "/bundles",
    response_model=AgentVersion,
    status_code=status.HTTP_201_CREATED,
)
async def publish_agent_bundle(
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AgentVersion:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/zip":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "agent_bundle_media_type_invalid",
                "message": "Agent bundles must use Content-Type application/zip",
            },
        )
    raw_length = request.headers.get("content-length")
    if raw_length is not None:
        try:
            content_length = int(raw_length)
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > MAX_AGENT_BUNDLE_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "agent_bundle_too_large",
                    "message": (
                        "Agent bundle exceeds maximum size of "
                        f"{MAX_AGENT_BUNDLE_UPLOAD_BYTES} bytes"
                    ),
                },
            )
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_AGENT_BUNDLE_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "agent_bundle_too_large",
                    "message": (
                        "Agent bundle exceeds maximum size of "
                        f"{MAX_AGENT_BUNDLE_UPLOAD_BYTES} bytes"
                    ),
                },
            )
    return await container.agents.publish_bundle(identity.tenant_id, bytes(content))
