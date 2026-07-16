from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends

from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    get_container,
    require_identity,
    require_owned_run,
)
from harness.api.schemas import ApprovalDecisionRequest
from harness.core.models import ApprovalRequest

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.put("/{approval_id}", response_model=ApprovalRequest)
async def decide_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    background_tasks: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> ApprovalRequest:
    ensure_permission(identity, "tasks:write")
    current = await container.approvals.get(identity.tenant_id, approval_id)
    await require_owned_run(container, identity, current.run_id)
    inline_waiting = container.approvals.has_inline_waiter(approval_id)
    approval = await container.approvals.decide(
        tenant_id=identity.tenant_id,
        approval_id=approval_id,
        decision=body.decision,
    )
    if (
        container.auto_execute
        and body.decision.value == "approved"
        and not inline_waiting
    ):
        background_tasks.add_task(container.worker.execute, identity.tenant_id, approval.run_id)
    return approval
