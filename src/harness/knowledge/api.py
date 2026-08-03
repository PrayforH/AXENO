from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from harness.knowledge.models import (
    CreateKnowledgeBaseRequest,
    CreateKnowledgeSourceRequest,
    CreateKnowledgeSourceResult,
    KnowledgeBase,
    KnowledgeSnapshot,
    KnowledgeSourceSummary,
    KnowledgeSyncRun,
    ReplaceKnowledgeBaseRequest,
    ReplaceKnowledgeSourceRequest,
    SearchKnowledgeRequest,
    SearchKnowledgeResponse,
)
from harness.knowledge.service import KnowledgeService
from harness.studio.api import (
    StudioActor,
    require_studio_reader,
    require_studio_writer,
)

router = APIRouter(prefix="/v1/studio/knowledge", tags=["knowledge"])


def get_knowledge_service(request: Request) -> KnowledgeService:
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "knowledge", None)
    if not isinstance(service, KnowledgeService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "knowledge_not_configured",
                "message": "Knowledge control plane is not configured",
            },
        )
    return service


@router.get("/bases", response_model=list[KnowledgeBase])
async def list_knowledge_bases(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> list[KnowledgeBase]:
    return list(await service.list_bases(actor.tenant_id, actor.user_id))


@router.post(
    "/bases",
    response_model=KnowledgeBase,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base(
    body: CreateKnowledgeBaseRequest,
    actor: Annotated[StudioActor, Depends(require_studio_writer)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeBase:
    return await service.create_base(actor.tenant_id, actor.user_id, body)


@router.get("/bases/{reference}", response_model=KnowledgeBase)
async def get_knowledge_base(
    reference: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeBase:
    return await service.get_base(actor.tenant_id, reference, actor.user_id)


@router.put("/bases/{reference}", response_model=KnowledgeBase)
async def replace_knowledge_base(
    reference: str,
    body: ReplaceKnowledgeBaseRequest,
    actor: Annotated[StudioActor, Depends(require_studio_writer)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeBase:
    return await service.replace_base(
        actor.tenant_id,
        actor.user_id,
        reference,
        body,
    )


@router.get("/sources", response_model=list[KnowledgeSourceSummary])
async def list_knowledge_sources(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> list[KnowledgeSourceSummary]:
    return [
        KnowledgeSourceSummary.from_source(source)
        for source in await service.list_sources(actor.tenant_id, actor.user_id)
    ]


@router.post(
    "/sources",
    response_model=CreateKnowledgeSourceResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_source(
    body: CreateKnowledgeSourceRequest,
    actor: Annotated[StudioActor, Depends(require_studio_writer)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> CreateKnowledgeSourceResult:
    source, sync = await service.create_source(
        actor.tenant_id,
        actor.user_id,
        body,
    )
    return CreateKnowledgeSourceResult(
        source=KnowledgeSourceSummary.from_source(source),
        sync=sync,
    )


@router.get("/sources/{reference}", response_model=KnowledgeSourceSummary)
async def get_knowledge_source(
    reference: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeSourceSummary:
    return KnowledgeSourceSummary.from_source(
        await service.get_source(actor.tenant_id, reference, actor.user_id)
    )


@router.put("/sources/{reference}", response_model=KnowledgeSourceSummary)
async def replace_knowledge_source(
    reference: str,
    body: ReplaceKnowledgeSourceRequest,
    actor: Annotated[StudioActor, Depends(require_studio_writer)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeSourceSummary:
    return KnowledgeSourceSummary.from_source(
        await service.replace_source(
            actor.tenant_id,
            actor.user_id,
            reference,
            body,
        )
    )


@router.post("/sources/{reference}/sync", response_model=KnowledgeSyncRun)
async def sync_knowledge_source(
    reference: str,
    actor: Annotated[StudioActor, Depends(require_studio_writer)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeSyncRun:
    return await service.sync_source(actor.tenant_id, actor.user_id, reference)


@router.get("/syncs", response_model=list[KnowledgeSyncRun])
async def list_knowledge_syncs(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    source_reference: str | None = None,
    limit: int = 100,
) -> list[KnowledgeSyncRun]:
    return list(
        await service.list_syncs(
            actor.tenant_id,
            actor.user_id,
            source_reference=source_reference,
            limit=max(1, min(limit, 200)),
        )
    )


@router.get("/snapshots", response_model=list[KnowledgeSnapshot])
async def list_knowledge_snapshots(
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    source_reference: str | None = None,
    limit: int = 100,
) -> list[KnowledgeSnapshot]:
    return list(
        await service.list_snapshots(
            actor.tenant_id,
            actor.user_id,
            source_reference=source_reference,
            limit=max(1, min(limit, 200)),
        )
    )


@router.get(
    "/citations/{snapshot_id}/{chunk_id}",
    response_class=PlainTextResponse,
)
async def open_knowledge_citation(
    snapshot_id: str,
    chunk_id: str,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> PlainTextResponse:
    chunk = await service.get_visible_chunk(
        actor.tenant_id,
        actor.user_id,
        snapshot_id,
        chunk_id,
    )
    filename = quote(f"{chunk.title}.txt", safe="")
    return PlainTextResponse(
        chunk.content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
            "X-Knowledge-Source": chunk.source_reference,
            "X-Knowledge-Document": chunk.document_id,
        },
    )


@router.post("/search", response_model=SearchKnowledgeResponse)
async def search_knowledge(
    body: SearchKnowledgeRequest,
    actor: Annotated[StudioActor, Depends(require_studio_reader)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> SearchKnowledgeResponse:
    return await service.search(
        actor.tenant_id,
        actor.user_id,
        body.query,
        knowledge_base_references=body.knowledge_base_references,
        limit=body.limit,
    )
