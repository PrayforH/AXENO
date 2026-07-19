"""Studio management and public invocation routes for Agent triggers."""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)

from harness.api.dependencies import Identity, ensure_permission, require_identity
from harness.core.models import Run
from harness.triggers.models import (
    AgentTrigger,
    CreateAgentTriggerRequest,
    CreatedAgentTrigger,
    InvokeAgentTriggerRequest,
    RotateAgentTriggerSecretRequest,
    TriggerInvocation,
    UpdateAgentTriggerRequest,
)
from harness.triggers.service import AgentTriggerService, TriggerAuthenticationError


def get_trigger_service(request: Request) -> AgentTriggerService:
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "triggers", None)
    if not isinstance(service, AgentTriggerService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "trigger_control_plane_not_configured",
                "message": "Agent Trigger control plane is not configured",
            },
        )
    return service


def require_trigger_admin(
    identity: Annotated[Identity, Depends(require_identity)],
) -> Identity:
    ensure_permission(identity, "studio:triggers:write")
    return identity


studio_router = APIRouter(prefix="/v1/studio", tags=["agent-triggers"])
public_router = APIRouter(prefix="/webhooks/agent-triggers", tags=["agent-trigger-invocation"])


@studio_router.get(
    "/agents/{agent_name}/triggers",
    response_model=list[AgentTrigger],
)
async def list_agent_triggers(
    agent_name: str,
    identity: Annotated[Identity, Depends(require_identity)],
    service: Annotated[AgentTriggerService, Depends(get_trigger_service)],
) -> list[AgentTrigger]:
    ensure_permission(identity, "studio:read")
    return await service.list(identity.tenant_id, agent_name)


@studio_router.post(
    "/agents/{agent_name}/triggers",
    response_model=CreatedAgentTrigger,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_trigger(
    agent_name: str,
    body: CreateAgentTriggerRequest,
    identity: Annotated[Identity, Depends(require_trigger_admin)],
    service: Annotated[AgentTriggerService, Depends(get_trigger_service)],
) -> CreatedAgentTrigger:
    return await service.create(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        agent_name=agent_name,
        request=body,
    )


@studio_router.put(
    "/triggers/{trigger_id}",
    response_model=AgentTrigger,
)
async def update_agent_trigger(
    trigger_id: str,
    body: UpdateAgentTriggerRequest,
    identity: Annotated[Identity, Depends(require_trigger_admin)],
    service: Annotated[AgentTriggerService, Depends(get_trigger_service)],
) -> AgentTrigger:
    return await service.update(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        trigger_id=trigger_id,
        request=body,
    )


@studio_router.post(
    "/triggers/{trigger_id}/rotate-secret",
    response_model=CreatedAgentTrigger,
)
async def rotate_agent_trigger_secret(
    trigger_id: str,
    body: RotateAgentTriggerSecretRequest,
    identity: Annotated[Identity, Depends(require_trigger_admin)],
    service: Annotated[AgentTriggerService, Depends(get_trigger_service)],
) -> CreatedAgentTrigger:
    return await service.rotate_secret(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        trigger_id=trigger_id,
        expected_revision=body.expected_revision,
    )


@public_router.post(
    "/{trigger_id}",
    response_model=TriggerInvocation,
    status_code=status.HTTP_202_ACCEPTED,
)
async def invoke_agent_trigger(
    trigger_id: str,
    body: InvokeAgentTriggerRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    service: Annotated[AgentTriggerService, Depends(get_trigger_service)],
    authorization: Annotated[str, Header(alias="Authorization")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
) -> TriggerInvocation:
    invocation, run = await _invoke(
        service,
        trigger_id=trigger_id,
        authorization=authorization,
        idempotency_key=idempotency_key,
        prompt=body.prompt,
    )
    container = request.app.state.container
    if container.auto_execute:
        background_tasks.add_task(container.worker.execute, run.tenant_id, run.run_id)
    return invocation


@public_router.get(
    "/{trigger_id}/runs/{run_id}",
    response_model=Run,
)
async def get_agent_trigger_run(
    trigger_id: str,
    run_id: str,
    service: Annotated[AgentTriggerService, Depends(get_trigger_service)],
    authorization: Annotated[str, Header(alias="Authorization")],
) -> Run:
    try:
        return await service.run(
            trigger_id=trigger_id,
            secret=_bearer_secret(authorization),
            run_id=run_id,
        )
    except TriggerAuthenticationError as error:
        raise _authentication_error() from error


async def _invoke(
    service: AgentTriggerService,
    *,
    trigger_id: str,
    authorization: str,
    idempotency_key: str,
    prompt: str,
) -> tuple[TriggerInvocation, Run]:
    try:
        return await service.invoke(
            trigger_id=trigger_id,
            secret=_bearer_secret(authorization),
            idempotency_key=idempotency_key,
            prompt=prompt,
        )
    except TriggerAuthenticationError as error:
        raise _authentication_error() from error


def _bearer_secret(authorization: str) -> str:
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not credential:
        raise _authentication_error()
    return credential


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "trigger_authentication_failed",
            "message": "Trigger authentication failed",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )
