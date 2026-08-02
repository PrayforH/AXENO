from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from harness.agent_package import MAX_AGENT_BUNDLE_UPLOAD_BYTES
from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    get_container,
    require_identity,
)
from harness.api.schemas import AgentCatalogItem, PublishAgentRequest
from harness.core.models import AgentVersion

router = APIRouter(prefix="/agents", tags=["agents"])


def _manifest_mapping(version: AgentVersion) -> dict[str, object]:
    manifest = version.snapshot.get("manifest")
    return cast(dict[str, object], manifest) if isinstance(manifest, dict) else {}


def _subagent_coordinates(version: AgentVersion) -> set[str]:
    spec = _manifest_mapping(version).get("spec")
    if not isinstance(spec, dict):
        return set()
    subagents = cast(dict[str, object], spec).get("subagents")
    if not isinstance(subagents, list):
        return set()
    coordinates: set[str] = set()
    for item in cast(list[object], subagents):
        if not isinstance(item, dict):
            continue
        reference = cast(dict[str, object], item).get("ref")
        if isinstance(reference, str):
            coordinates.add(reference)
    return coordinates


def _is_internal(version: AgentVersion) -> bool:
    metadata = _manifest_mapping(version).get("metadata")
    labels = cast(dict[str, object], metadata).get("labels") if isinstance(metadata, dict) else None
    if not isinstance(labels, dict):
        return False
    return cast(dict[str, object], labels).get("visibility") == "internal"


@router.get("", response_model=list[AgentCatalogItem])
async def list_agents(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> list[AgentCatalogItem]:
    ensure_permission(identity, "tasks:read")
    versions = await container.agents.list_published(identity.tenant_id, identity.user_id)
    dependency_coordinates = {
        coordinate for version in versions for coordinate in _subagent_coordinates(version)
    }
    return [
        AgentCatalogItem.from_version(version)
        for version in versions
        if f"{version.name}@{version.version}" not in dependency_coordinates
        and not _is_internal(version)
    ]


@router.post("", response_model=AgentVersion, status_code=status.HTTP_201_CREATED)
async def publish_agent(
    body: PublishAgentRequest,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AgentVersion:
    ensure_permission(identity, "agents:publish")
    if not container.agents.path_publication_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_path_publication_disabled",
                "message": "production accepts reproducible Agent bundles, not server-local paths",
            },
        )
    return await container.agents.publish(identity.tenant_id, identity.user_id, body.path)


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
    ensure_permission(identity, "agents:publish")
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
    return await container.agents.publish_bundle(
        identity.tenant_id, identity.user_id, bytes(content)
    )
