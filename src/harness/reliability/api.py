from typing import Annotated

from fastapi import APIRouter, Depends

from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    get_container,
    require_identity,
)
from harness.reliability.models import ReliabilityOverview

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/overview", response_model=ReliabilityOverview)
async def overview(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> ReliabilityOverview:
    ensure_permission(identity, "operations:read")
    return await container.reliability.overview(identity.tenant_id)


@router.post("/reconcile", response_model=dict[str, int])
async def reconcile(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> dict[str, int]:
    ensure_permission(identity, "operations:admin")
    return {"reaped": await container.reliability_controller.process_once()}
