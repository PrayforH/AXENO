from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    get_container,
    require_identity,
    require_owned_run,
)
from harness.api.downloads import attachment_content_disposition
from harness.core.models import Artifact

router = APIRouter(tags=["artifacts"])


@router.post(
    "/runs/{run_id}/artifacts",
    response_model=Artifact,
    status_code=status.HTTP_201_CREATED,
)
async def upload_artifact(
    run_id: str,
    file: Annotated[UploadFile, File()],
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Artifact:
    ensure_permission(identity, "tasks:write")
    await require_owned_run(container, identity, run_id)
    maximum = container.artifacts.max_file_bytes
    content = await file.read(maximum + 1)
    if len(content) > maximum:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "artifact_too_large",
                "message": f"artifact exceeds maximum size of {maximum} bytes",
            },
        )
    return await container.artifacts.upload(
        tenant_id=identity.tenant_id,
        run_id=run_id,
        name=file.filename or "artifact",
        media_type=file.content_type or "application/octet-stream",
        content=content,
    )


@router.get("/runs/{run_id}/artifacts", response_model=list[Artifact])
async def list_artifacts(
    run_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> list[Artifact]:
    ensure_permission(identity, "tasks:read")
    await require_owned_run(container, identity, run_id)
    return await container.artifacts.list_for_run(identity.tenant_id, run_id)


@router.get("/artifacts/{artifact_id}/content")
async def download_artifact(
    artifact_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Response:
    ensure_permission(identity, "tasks:read")
    artifact = await container.artifacts.get(identity.tenant_id, artifact_id)
    await require_owned_run(container, identity, artifact.run_id)
    artifact, content = await container.artifacts.download(identity.tenant_id, artifact_id)
    return Response(
        content=content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": attachment_content_disposition(artifact.name)
        },
    )
