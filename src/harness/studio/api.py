"""Standalone Agent Studio API contract backed by trusted Harness identities.

The router remains intentionally unmounted until the control-plane composition work is
complete. Applications that mount it must provide the normal Harness API container and
authentication middleware; Studio never accepts a client-supplied actor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response

from harness.api.dependencies import Identity, ensure_permission, require_identity
from harness.core.errors import ConflictError, NotFoundError
from harness.core.models import AgentVersion
from harness.studio.compiler import DraftCompilationError
from harness.studio.models import (
    AgentDraft,
    AgentDraftSummary,
    CapabilityCatalog,
    CreateAgentDraftRequest,
    DraftValidationResult,
    ReplaceAgentDraftRequest,
)
from harness.studio.service import AgentStudioService, StudioPublisherNotConfiguredError


@dataclass(frozen=True)
class StudioActor:
    tenant_id: str
    user_id: str


def _authorize_studio_actor(identity: Identity, permission: str) -> StudioActor:
    ensure_permission(identity, permission)
    return StudioActor(tenant_id=identity.tenant_id, user_id=identity.user_id)


def require_studio_reader(
    identity: Annotated[Identity, Depends(require_identity)],
) -> StudioActor:
    return _authorize_studio_actor(identity, "studio:read")


def require_studio_writer(
    identity: Annotated[Identity, Depends(require_identity)],
) -> StudioActor:
    return _authorize_studio_actor(identity, "studio:write")


def require_studio_publisher(
    identity: Annotated[Identity, Depends(require_identity)],
) -> StudioActor:
    return _authorize_studio_actor(identity, "studio:publish")


def get_studio_service(request: Request) -> AgentStudioService:
    service = getattr(request.app.state, "agent_studio", None)
    if not isinstance(service, AgentStudioService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "studio_not_configured",
                "message": "Agent Studio control plane is not configured",
            },
        )
    return service


router = APIRouter(prefix="/v1/studio", tags=["agent-studio"])


def _translate_domain_error(error: Exception) -> HTTPException:
    if isinstance(error, NotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": str(error)},
        )
    if isinstance(error, ConflictError):
        return HTTPException(
            status_code=409,
            detail={"code": "draft_conflict", "message": str(error)},
        )
    raise error


@router.get("/capabilities", response_model=CapabilityCatalog)
async def capabilities(
    _actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> CapabilityCatalog:
    return service.catalog


@router.get("/drafts", response_model=list[AgentDraftSummary])
async def list_drafts(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> list[AgentDraftSummary]:
    return await service.list(actor.tenant_id)


@router.post(
    "/drafts", response_model=AgentDraft, status_code=status.HTTP_201_CREATED
)
async def create_draft(
    body: CreateAgentDraftRequest,
    actor: Annotated[StudioActor, Depends(require_studio_writer)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> AgentDraft:
    try:
        return await service.create(
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            request=body,
        )
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error


@router.get("/drafts/{draft_id}", response_model=AgentDraft)
async def get_draft(
    draft_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> AgentDraft:
    try:
        return await service.get(actor.tenant_id, draft_id)
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error


@router.put("/drafts/{draft_id}", response_model=AgentDraft)
async def replace_draft(
    draft_id: str,
    body: ReplaceAgentDraftRequest,
    actor: Annotated[StudioActor, Depends(require_studio_writer)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> AgentDraft:
    try:
        return await service.replace(
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            draft_id=draft_id,
            request=body,
        )
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error


@router.post("/drafts/{draft_id}/validate", response_model=DraftValidationResult)
async def validate_draft(
    draft_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_writer)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> DraftValidationResult:
    try:
        return await service.validate(actor.tenant_id, draft_id)
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error


@router.get("/drafts/{draft_id}/bundle")
async def download_bundle(
    draft_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> Response:
    try:
        compiled = await service.bundle(actor.tenant_id, draft_id)
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error
    except DraftCompilationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "draft_not_ready",
                "message": str(error),
                "issues": [
                    issue.model_dump(mode="json", by_alias=True)
                    for issue in error.issues
                ],
            },
        ) from error
    return Response(
        content=compiled.bundle,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{compiled.filename}"'
        },
    )


@router.post("/drafts/{draft_id}/publish", response_model=AgentVersion)
async def publish_draft(
    draft_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_publisher)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> AgentVersion:
    try:
        return await service.publish(
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            draft_id=draft_id,
        )
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error
    except DraftCompilationError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "draft_not_ready", "message": str(error)},
        ) from error
    except StudioPublisherNotConfiguredError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "studio_publisher_unavailable", "message": str(error)},
        ) from error
