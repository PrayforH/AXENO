from typing import Annotated

from fastapi import APIRouter, Depends

from harness.api.dependencies import ApiContainer, Identity, get_container, require_identity
from harness.api.schemas import ApprovalDecisionRequest
from harness.core.models import ApprovalRequest

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.put("/{approval_id}", response_model=ApprovalRequest)
async def decide_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> ApprovalRequest:
    return await container.approvals.decide(
        tenant_id=identity.tenant_id,
        approval_id=approval_id,
        decision=body.decision,
    )
