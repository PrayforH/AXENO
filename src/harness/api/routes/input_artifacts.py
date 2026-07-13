from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from harness.api.dependencies import ApiContainer, Identity, get_container, require_identity
from harness.core.errors import NotFoundError
from harness.core.models import InputArtifact, ThreadFile

router = APIRouter(tags=["input-artifacts"])


@router.get("/threads/{session_id}/files", response_model=list[ThreadFile])
async def list_thread_files(
    session_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> list[ThreadFile]:
    session = await container.sessions.get(identity.tenant_id, session_id)
    if session.user_id != identity.user_id:
        raise NotFoundError(f"session not found: {session_id}")
    return await container.file_catalog.list_scope(
        identity.tenant_id, identity.user_id, session_id
    )


@router.post(
    "/input-artifacts",
    response_model=InputArtifact,
    status_code=status.HTTP_201_CREATED,
)
async def upload_input_artifact(
    file: Annotated[UploadFile, File()],
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> InputArtifact:
    maximum = container.input_artifacts.max_file_bytes
    content = await file.read(maximum + 1)
    if len(content) > maximum:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "input_artifact_too_large",
                "message": f"input artifact exceeds maximum size of {maximum} bytes",
            },
        )
    return await container.input_artifacts.upload(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        name=file.filename or "input",
        media_type=file.content_type or "application/octet-stream",
        content=content,
    )


@router.get("/input-artifacts/{input_artifact_id}/content")
async def download_input_artifact(
    input_artifact_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Response:
    artifact, content = await container.input_artifacts.download(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        input_artifact_id=input_artifact_id,
    )
    return Response(
        content=content,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.name}"'},
    )
