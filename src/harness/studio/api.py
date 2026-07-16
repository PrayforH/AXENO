"""Agent Studio API contract backed by trusted Harness identities."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response

from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    require_identity,
)
from harness.core.errors import ConflictError, NotFoundError
from harness.evals.controller import EvalController
from harness.evals.models import (
    CreateEvalDatasetVersionRequest,
    CreateEvalRunRequest,
    EvalDatasetVersion,
    EvalGateResult,
    EvalRunView,
)
from harness.evals.service import EvalControlPlaneService
from harness.studio.catalog_service import CapabilityCatalogService, CatalogResourceType
from harness.studio.compiler import DraftCompilationError
from harness.studio.models import (
    AgentDraft,
    AgentDraftSummary,
    CapabilityCatalog,
    CapabilityCatalogRecord,
    CatalogImpact,
    CatalogMutationResult,
    CreateAgentDraftRequest,
    DraftValidationResult,
    PublishAgentDraftRequest,
    PublishedAgentVersion,
    ReplaceAgentDraftRequest,
    ReplaceCapabilityCatalogRequest,
    UpsertCatalogResourceRequest,
)
from harness.studio.preflight_models import PreflightEvent
from harness.studio.preview_controller import PreviewController
from harness.studio.preview_models import CreatePreviewRequest, PreviewDeployment
from harness.studio.preview_service import PreviewService
from harness.studio.service import (
    AgentStudioService,
    StudioPublicationConflictError,
    StudioPublisherNotConfiguredError,
)


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


def require_studio_previewer(
    identity: Annotated[Identity, Depends(require_identity)],
) -> StudioActor:
    return _authorize_studio_actor(identity, "studio:preview")


def require_studio_catalog_admin(
    identity: Annotated[Identity, Depends(require_identity)],
) -> StudioActor:
    return _authorize_studio_actor(identity, "studio:catalog:write")


def get_studio_service(request: Request) -> AgentStudioService:
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "studio", None)
    if not isinstance(service, AgentStudioService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "studio_not_configured",
                "message": "Agent Studio control plane is not configured",
            },
        )
    return service


def get_catalog_service(request: Request) -> CapabilityCatalogService:
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "capability_catalogs", None)
    if not isinstance(service, CapabilityCatalogService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "catalog_not_configured",
                "message": "Capability Catalog is not configured",
            },
        )
    return service


def get_preview_service(request: Request) -> PreviewService:
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "previews", None)
    if not isinstance(service, PreviewService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "preview_not_configured",
                "message": "Studio Preview control plane is not configured",
            },
        )
    return service


def get_preview_controller(request: Request) -> PreviewController:
    container = getattr(request.app.state, "container", None)
    controller = getattr(container, "preview_controller", None)
    if not isinstance(controller, PreviewController):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "preview_controller_not_configured",
                "message": "Studio Preview controller is not configured",
            },
        )
    return controller


def get_eval_service(request: Request) -> EvalControlPlaneService:
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "evals", None)
    if not isinstance(service, EvalControlPlaneService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "eval_control_plane_not_configured",
                "message": "Studio Eval control plane is not configured",
            },
        )
    return service


def get_eval_controller(request: Request) -> EvalController:
    container = getattr(request.app.state, "container", None)
    controller = getattr(container, "eval_controller", None)
    if not isinstance(controller, EvalController):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "eval_controller_not_configured",
                "message": "Studio Eval controller is not configured",
            },
        )
    return controller


router = APIRouter(prefix="/v1/studio", tags=["agent-studio"])


@router.post(
    "/eval-datasets",
    response_model=EvalDatasetVersion,
    status_code=status.HTTP_201_CREATED,
)
async def create_eval_dataset(
    body: CreateEvalDatasetVersionRequest,
    actor: Annotated[StudioActor, Depends(require_studio_writer)],
    service: Annotated[EvalControlPlaneService, Depends(get_eval_service)],
) -> EvalDatasetVersion:
    try:
        return await service.create_dataset_version(
            tenant_id=actor.tenant_id, user_id=actor.user_id, request=body
        )
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error
    except DraftCompilationError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "draft_not_ready", "message": str(error)},
        ) from error


@router.get("/eval-datasets", response_model=list[EvalDatasetVersion])
async def list_eval_datasets(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[EvalControlPlaneService, Depends(get_eval_service)],
) -> list[EvalDatasetVersion]:
    return await service.list_datasets(actor.tenant_id)


@router.get(
    "/eval-datasets/{dataset_id}/versions/{version}",
    response_model=EvalDatasetVersion,
)
async def get_eval_dataset(
    dataset_id: str,
    version: int,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[EvalControlPlaneService, Depends(get_eval_service)],
) -> EvalDatasetVersion:
    try:
        return await service.get_dataset(actor.tenant_id, dataset_id, version)
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error


@router.post(
    "/eval-runs", response_model=EvalRunView, status_code=status.HTTP_202_ACCEPTED
)
async def create_eval_run(
    body: CreateEvalRunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    actor: Annotated[StudioActor, Depends(require_studio_previewer)],
    service: Annotated[EvalControlPlaneService, Depends(get_eval_service)],
    controller: Annotated[EvalController, Depends(get_eval_controller)],
) -> EvalRunView:
    try:
        result = await service.create_run(
            tenant_id=actor.tenant_id, user_id=actor.user_id, request=body
        )
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error
    container = getattr(request.app.state, "container", None)
    if getattr(container, "auto_execute", False):
        assert isinstance(container, ApiContainer)
        background_tasks.add_task(
            controller.drain_locally,
            actor.tenant_id,
            result.run.eval_run_id,
            run_queue=container.task_queue,
            executor=container.worker,
        )
    return result


@router.get("/eval-runs", response_model=list[EvalRunView])
async def list_eval_runs(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[EvalControlPlaneService, Depends(get_eval_service)],
) -> list[EvalRunView]:
    return await service.list_runs(actor.tenant_id)


@router.get("/eval-runs/{eval_run_id}", response_model=EvalRunView)
async def get_eval_run(
    eval_run_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[EvalControlPlaneService, Depends(get_eval_service)],
) -> EvalRunView:
    try:
        return await service.get_run(actor.tenant_id, eval_run_id)
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error


@router.post("/eval-runs/{eval_run_id}/cancel", response_model=EvalRunView)
async def cancel_eval_run(
    eval_run_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    actor: Annotated[StudioActor, Depends(require_studio_previewer)],
    service: Annotated[EvalControlPlaneService, Depends(get_eval_service)],
    controller: Annotated[EvalController, Depends(get_eval_controller)],
) -> EvalRunView:
    try:
        result = await service.cancel_run(
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            eval_run_id=eval_run_id,
        )
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error
    container = getattr(request.app.state, "container", None)
    if getattr(container, "auto_execute", False):
        assert isinstance(container, ApiContainer)
        background_tasks.add_task(
            controller.drain_locally,
            actor.tenant_id,
            eval_run_id,
            run_queue=container.task_queue,
            executor=container.worker,
        )
    return result


@router.get("/eval-runs/{eval_run_id}/artifacts/{artifact_id}")
async def download_eval_artifact(
    eval_run_id: str,
    artifact_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[EvalControlPlaneService, Depends(get_eval_service)],
) -> Response:
    try:
        name, media_type, content = await service.download_artifact(
            actor.tenant_id, eval_run_id, artifact_id
        )
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get(
    "/evaluation-gates/{agent_name}/versions/{agent_version}",
    response_model=EvalGateResult,
)
async def get_eval_gate(
    agent_name: str,
    agent_version: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[EvalControlPlaneService, Depends(get_eval_service)],
) -> EvalGateResult:
    return await service.gate(actor.tenant_id, agent_name, agent_version)


@router.get("/catalog", response_model=CapabilityCatalogRecord)
async def get_catalog(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[CapabilityCatalogService, Depends(get_catalog_service)],
) -> CapabilityCatalogRecord:
    return await service.get(actor.tenant_id)


@router.put("/catalog", response_model=CapabilityCatalogRecord)
async def replace_catalog(
    body: ReplaceCapabilityCatalogRequest,
    actor: Annotated[StudioActor, Depends(require_studio_catalog_admin)],
    service: Annotated[CapabilityCatalogService, Depends(get_catalog_service)],
) -> CapabilityCatalogRecord:
    return await service.replace(
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        request=body,
    )


@router.get(
    "/catalog/{resource_type}/{resource_id}/impact",
    response_model=CatalogImpact,
)
async def catalog_impact(
    resource_type: CatalogResourceType,
    resource_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[CapabilityCatalogService, Depends(get_catalog_service)],
) -> CatalogImpact:
    return await service.impact(actor.tenant_id, resource_type, resource_id)


@router.delete(
    "/catalog/{resource_type}/{resource_id}",
    response_model=CatalogMutationResult,
)
async def disable_catalog_resource(
    resource_type: CatalogResourceType,
    resource_id: str,
    expected_revision: int,
    actor: Annotated[StudioActor, Depends(require_studio_catalog_admin)],
    service: Annotated[CapabilityCatalogService, Depends(get_catalog_service)],
) -> CatalogMutationResult:
    return await service.disable(
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        expected_revision=expected_revision,
    )


@router.put(
    "/catalog/{resource_type}/{resource_id}",
    response_model=CatalogMutationResult,
)
async def upsert_catalog_resource(
    resource_type: CatalogResourceType,
    resource_id: str,
    body: UpsertCatalogResourceRequest,
    actor: Annotated[StudioActor, Depends(require_studio_catalog_admin)],
    service: Annotated[CapabilityCatalogService, Depends(get_catalog_service)],
) -> CatalogMutationResult:
    return await service.upsert(
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        request=body,
    )


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
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> CapabilityCatalog:
    return await service.capabilities(actor.tenant_id)


@router.get("/drafts", response_model=list[AgentDraftSummary])
async def list_drafts(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
) -> list[AgentDraftSummary]:
    return await service.list(actor.tenant_id)


@router.post(
    "/previews",
    response_model=PreviewDeployment,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_preview(
    body: CreatePreviewRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    actor: Annotated[StudioActor, Depends(require_studio_previewer)],
    service: Annotated[PreviewService, Depends(get_preview_service)],
    controller: Annotated[PreviewController, Depends(get_preview_controller)],
) -> PreviewDeployment:
    try:
        preview = await service.create(
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            request=body,
        )
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
    container = getattr(request.app.state, "container", None)
    if getattr(container, "auto_execute", False):
        background_tasks.add_task(controller.process_once)
    return preview


@router.get("/previews", response_model=list[PreviewDeployment])
async def list_previews(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[PreviewService, Depends(get_preview_service)],
) -> list[PreviewDeployment]:
    return await service.list(actor.tenant_id)


@router.get("/previews/{preview_id}", response_model=PreviewDeployment)
async def get_preview(
    preview_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[PreviewService, Depends(get_preview_service)],
) -> PreviewDeployment:
    try:
        return await service.get(actor.tenant_id, preview_id)
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error


@router.get(
    "/previews/{preview_id}/events",
    response_model=list[PreflightEvent],
)
async def get_preview_events(
    preview_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[PreviewService, Depends(get_preview_service)],
) -> list[PreflightEvent]:
    try:
        preview = await service.get(actor.tenant_id, preview_id)
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error
    return list(preview.preflight_result.events) if preview.preflight_result else []


@router.post("/previews/{preview_id}/cancel", response_model=PreviewDeployment)
async def cancel_preview(
    preview_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    actor: Annotated[StudioActor, Depends(require_studio_previewer)],
    service: Annotated[PreviewService, Depends(get_preview_service)],
    controller: Annotated[PreviewController, Depends(get_preview_controller)],
) -> PreviewDeployment:
    try:
        preview = await service.cancel(
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            preview_id=preview_id,
        )
    except (ConflictError, NotFoundError) as error:
        raise _translate_domain_error(error) from error
    container = getattr(request.app.state, "container", None)
    if getattr(container, "auto_execute", False):
        background_tasks.add_task(controller.process_once)
    return preview


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
            "Content-Disposition": f'attachment; filename="{compiled.filename}"',
            "ETag": f'"{hashlib.sha256(compiled.bundle).hexdigest()}"',
            "X-Agent-Content-SHA256": compiled.report.snapshot.content_hash,
            "X-Agent-Package-SHA256": compiled.report.package_hash,
        },
    )


@router.post("/drafts/{draft_id}/publish", response_model=PublishedAgentVersion)
async def publish_draft(
    draft_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_publisher)],
    service: Annotated[AgentStudioService, Depends(get_studio_service)],
    body: PublishAgentDraftRequest | None = None,
) -> PublishedAgentVersion:
    try:
        version = await service.publish(
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            draft_id=draft_id,
            expected_revision=(body.expected_revision if body is not None else None),
        )
        return PublishedAgentVersion.model_validate(
            version.model_dump(exclude={"snapshot"})
        )
    except StudioPublicationConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "version_conflict", "message": str(error)},
        ) from error
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
    except StudioPublisherNotConfiguredError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "studio_publisher_unavailable", "message": str(error)},
        ) from error
