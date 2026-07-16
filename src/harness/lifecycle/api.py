"""Tenant-scoped retention, legal-hold, export and deletion API."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status

from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    get_container,
    require_identity,
    require_owned_session,
)
from harness.api.downloads import attachment_content_disposition
from harness.lifecycle.models import (
    CreateLegalHoldRequest,
    CreateLifecycleJobRequest,
    DataLifecycleJob,
    LegalHold,
    LifecycleJobKind,
    LifecycleOverview,
    LifecycleScopeKind,
    ReplaceRetentionPolicyRequest,
    RetentionPolicy,
)

router = APIRouter(prefix="/data-lifecycle", tags=["data-lifecycle"])


def _is_admin(identity: Identity) -> bool:
    return bool(identity.roles.intersection({"owner", "admin"}))


async def _authorize_job_scope(
    identity: Identity,
    container: ApiContainer,
    request: CreateLifecycleJobRequest,
) -> None:
    if _is_admin(identity):
        ensure_permission(identity, "data:lifecycle:admin")
        return
    ensure_permission(identity, "data:lifecycle:self")
    if request.kind is LifecycleJobKind.RETENTION:
        ensure_permission(identity, "data:lifecycle:admin")
    if request.scope.kind is LifecycleScopeKind.USER:
        if request.scope.subject_id != identity.user_id:
            ensure_permission(identity, "data:lifecycle:admin")
        return
    if request.scope.kind is LifecycleScopeKind.SESSION:
        await require_owned_session(container, identity, request.scope.subject_id)
        return
    ensure_permission(identity, "data:lifecycle:admin")


async def _authorize_existing_job(
    identity: Identity,
    container: ApiContainer,
    job: DataLifecycleJob,
) -> None:
    request = CreateLifecycleJobRequest(
        kind=job.kind,
        scope=job.scope,
        idempotencyKey=job.idempotency_key,
    )
    await _authorize_job_scope(identity, container, request)


@router.get("/overview", response_model=LifecycleOverview)
async def overview(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> LifecycleOverview:
    ensure_permission(identity, "data:lifecycle:admin")
    return await container.lifecycle.overview(identity.tenant_id)


@router.put("/retention-policy", response_model=RetentionPolicy)
async def replace_retention_policy(
    request: ReplaceRetentionPolicyRequest,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> RetentionPolicy:
    ensure_permission(identity, "data:lifecycle:admin")
    return await container.lifecycle.replace_policy(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        request=request,
    )


@router.post("/legal-holds", response_model=LegalHold, status_code=status.HTTP_201_CREATED)
async def create_legal_hold(
    request: CreateLegalHoldRequest,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> LegalHold:
    ensure_permission(identity, "data:lifecycle:admin")
    return await container.lifecycle.create_hold(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        request=request,
    )


@router.post("/legal-holds/{hold_id}/release", response_model=LegalHold)
async def release_legal_hold(
    hold_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> LegalHold:
    ensure_permission(identity, "data:lifecycle:admin")
    return await container.lifecycle.release_hold(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        hold_id=hold_id,
    )


@router.post("/jobs", response_model=DataLifecycleJob, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: CreateLifecycleJobRequest,
    background_tasks: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> DataLifecycleJob:
    await _authorize_job_scope(identity, container, request)
    job = await container.lifecycle.create_job(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        request=request,
    )
    if container.auto_execute:
        background_tasks.add_task(container.lifecycle_controller.process_once)
    return job


@router.get("/jobs/{job_id}", response_model=DataLifecycleJob)
async def get_job(
    job_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> DataLifecycleJob:
    job = await container.lifecycle.get_job(identity.tenant_id, job_id)
    await _authorize_existing_job(identity, container, job)
    return job


@router.get("/self/jobs", response_model=list[DataLifecycleJob])
async def list_self_jobs(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> list[DataLifecycleJob]:
    ensure_permission(identity, "data:lifecycle:self")
    jobs = await container.lifecycle.list_jobs(identity.tenant_id)
    return [item for item in jobs if item.requested_by == identity.user_id]


@router.post("/jobs/{job_id}/retry", response_model=DataLifecycleJob)
async def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> DataLifecycleJob:
    current = await container.lifecycle.get_job(identity.tenant_id, job_id)
    await _authorize_existing_job(identity, container, current)
    job = await container.lifecycle.retry_job(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        job_id=job_id,
    )
    if container.auto_execute:
        background_tasks.add_task(container.lifecycle_controller.process_once)
    return job


@router.get("/jobs/{job_id}/artifact")
async def download_export(
    job_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Response:
    job = await container.lifecycle.get_job(identity.tenant_id, job_id)
    await _authorize_existing_job(identity, container, job)
    job, content = await container.lifecycle.download_export(identity.tenant_id, job_id)
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": attachment_content_disposition(
                job.export_filename or "data-export.zip"
            )
        },
    )
