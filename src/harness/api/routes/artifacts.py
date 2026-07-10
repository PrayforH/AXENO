from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import Response

from harness.api.dependencies import ApiContainer, Identity, get_container, require_identity
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
    return await container.artifacts.upload(
        tenant_id=identity.tenant_id,
        run_id=run_id,
        name=file.filename or "artifact",
        media_type=file.content_type or "application/octet-stream",
        content=await file.read(),
    )


@router.get("/runs/{run_id}/artifacts", response_model=list[Artifact])
async def list_artifacts(
    run_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> list[Artifact]:
    return await container.artifacts.list_for_run(identity.tenant_id, run_id)


@router.get("/artifacts/{artifact_id}/content")
async def download_artifact(
    artifact_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Response:
    artifact, content = await container.artifacts.download(identity.tenant_id, artifact_id)
    return Response(
        content=content,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.name}"'},
    )
