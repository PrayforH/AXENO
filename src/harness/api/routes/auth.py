"""Public authentication endpoints and authenticated profile access."""

from typing import Annotated, Literal, TypedDict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    get_container,
    require_identity,
)
from harness.auth.models import AuditEntry, AuthSession, AuthUser, Membership
from harness.auth.service import AuthenticationError, RegistrationDisabledError
from harness.core.errors import ConflictError

router = APIRouter(prefix="/auth", tags=["authentication"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(default="", max_length=160)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=512)


class OAuthExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    redirect_uri: str = Field(min_length=8, max_length=2048)
    code_verifier: str = Field(min_length=43, max_length=128)


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class AuthProfile(BaseModel):
    user: AuthUser
    membership: Membership
    password_enabled: bool


class RequestContext(TypedDict):
    ip_address: str | None
    user_agent: str | None


def _request_context(request: Request) -> RequestContext:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


@router.get("/config")
async def auth_config(
    container: Annotated[ApiContainer, Depends(get_container)],
) -> dict[str, object]:
    return {
        "registration_enabled": container.auth.allow_registration,
        "providers": container.auth.provider_status(),
    }


@router.post("/register", response_model=AuthSession, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AuthSession:
    try:
        session = await container.auth.register(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    except RegistrationDisabledError as error:
        raise HTTPException(
            status_code=403,
            detail={"code": "registration_disabled", "message": str(error)},
        ) from error
    except ConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "account_exists", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "registration_invalid", "message": str(error)},
        ) from error
    await container.audit.record(
        tenant_id=session.membership.tenant_id,
        user_id=session.user.user_id,
        action="auth.register",
        resource_type="user",
        resource_id=session.user.user_id,
        **_request_context(request),
    )
    return session


@router.post("/login", response_model=AuthSession)
async def login(
    body: LoginRequest,
    request: Request,
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AuthSession:
    try:
        session = await container.auth.login(email=body.email, password=body.password)
    except AuthenticationError as error:
        await container.audit.record(
            tenant_id=None,
            user_id=None,
            action="auth.login",
            resource_type="user",
            outcome="denied",
            **_request_context(request),
        )
        raise HTTPException(
            status_code=401,
            detail={"code": "credentials_invalid", "message": str(error)},
        ) from error
    await container.audit.record(
        tenant_id=session.membership.tenant_id,
        user_id=session.user.user_id,
        action="auth.login",
        resource_type="user",
        resource_id=session.user.user_id,
        **_request_context(request),
    )
    return session


@router.post("/oauth/{provider}/exchange", response_model=AuthSession)
async def oauth_exchange(
    provider: Literal["google", "github"],
    body: OAuthExchangeRequest,
    request: Request,
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AuthSession:
    try:
        session = await container.auth.exchange_oauth_code(
            provider=provider,
            code=body.code,
            redirect_uri=body.redirect_uri,
            code_verifier=body.code_verifier,
        )
    except (AuthenticationError, httpx.HTTPError, KeyError) as error:
        await container.audit.record(
            tenant_id=None,
            user_id=None,
            action=f"auth.oauth.{provider}",
            resource_type="user",
            outcome="denied",
            **_request_context(request),
        )
        raise HTTPException(
            status_code=401,
            detail={"code": "oauth_exchange_failed", "message": "SSO sign-in failed"},
        ) from error
    await container.audit.record(
        tenant_id=session.membership.tenant_id,
        user_id=session.user.user_id,
        action=f"auth.oauth.{provider}",
        resource_type="user",
        resource_id=session.user.user_id,
        **_request_context(request),
    )
    return session


@router.post("/refresh", response_model=AuthSession)
async def refresh(
    body: RefreshRequest,
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AuthSession:
    try:
        return await container.auth.refresh(body.refresh_token)
    except AuthenticationError as error:
        raise HTTPException(
            status_code=401,
            detail={"code": "refresh_invalid", "message": str(error)},
        ) from error


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    container: Annotated[ApiContainer, Depends(get_container)],
) -> None:
    await container.auth.logout(body.refresh_token)


@router.get("/me", response_model=AuthProfile)
async def me(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AuthProfile:
    user, membership = await container.auth.profile(
        identity.tenant_id, identity.user_id
    )
    return AuthProfile(
        user=user,
        membership=membership,
        password_enabled=user.password_hash is not None,
    )


@router.patch("/me", response_model=AuthUser)
async def update_me(
    body: UpdateProfileRequest,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AuthUser:
    try:
        user = await container.auth.update_profile(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            display_name=body.display_name,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "profile_invalid", "message": str(error)},
        ) from error
    await container.audit.record(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        action="auth.profile.update",
        resource_type="user",
        resource_id=identity.user_id,
        **_request_context(request),
    )
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> None:
    try:
        await container.auth.change_password(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except AuthenticationError as error:
        await container.audit.record(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            action="auth.password.change",
            resource_type="user",
            resource_id=identity.user_id,
            outcome="denied",
            **_request_context(request),
        )
        raise HTTPException(
            status_code=401,
            detail={"code": "password_invalid", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "password_invalid", "message": str(error)},
        ) from error
    await container.audit.record(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        action="auth.password.change",
        resource_type="user",
        resource_id=identity.user_id,
        **_request_context(request),
    )


@router.get("/audit-logs", response_model=list[AuditEntry])
async def audit_logs(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
    limit: int = 100,
) -> list[AuditEntry]:
    ensure_permission(identity, "audit:read")
    return await container.audit.list_for_tenant(
        identity.tenant_id, limit=max(1, min(limit, 500))
    )
