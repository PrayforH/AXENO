"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from hmac import compare_digest

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from harness.agent_package import AgentBundleValidationError, AgentPackageCheckError
from harness.agui import routes as agui_routes
from harness.api.dependencies import ApiContainer, build_memory_container
from harness.api.routes import agents, approvals, artifacts, input_artifacts, runs, sessions
from harness.config import Settings
from harness.core.errors import HarnessDomainError, NotFoundError
from harness.core.manifest import ManifestValidationError


async def _http_error(_request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HTTPException)
    detail = error.detail
    if isinstance(detail, dict) and "code" in detail:
        payload = detail
    else:
        payload = {"code": "http_error", "message": str(detail)}
    return JSONResponse(status_code=error.status_code, content={"error": payload})


async def _domain_error(_request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HarnessDomainError)
    status_code = 404 if isinstance(error, NotFoundError) else 409
    code = "not_found" if status_code == 404 else "conflict"
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": str(error)}},
    )


async def _manifest_error(_request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ManifestValidationError)
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "manifest_invalid", "message": str(error)}},
    )


async def _agent_package_error(_request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, (AgentPackageCheckError, AgentBundleValidationError))
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "agent_package_invalid", "message": str(error)}},
    )


async def _trace_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
    container: ApiContainer = request.app.state.container
    with container.observability.span(
        "harness.api.request",
        attributes={"http.method": request.method, "http.route": request.url.path},
    ):
        return await call_next(request)


async def _authenticate_request(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    if not request.url.path.startswith("/v1"):
        return await call_next(request)
    container: ApiContainer = request.app.state.container
    expected = container.api_bearer_token.get_secret_value()
    if not expected:
        return await call_next(request)
    scheme, separator, credential = request.headers.get("Authorization", "").partition(
        " "
    )
    if (
        not separator
        or scheme.lower() != "bearer"
        or not compare_digest(credential, expected)
    ):
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "api_auth_required",
                    "message": "A valid Harness API credential is required",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


async def _healthz() -> dict[str, str]:
    return {"status": "ok"}


def create_app(container: ApiContainer) -> FastAPI:
    api_token = container.api_bearer_token.get_secret_value()
    if container.environment == "production" and len(api_token) < 32:
        raise ValueError(
            "production API requires HARNESS_API_BEARER_TOKEN with at least 32 characters"
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            if container.close is not None:
                await container.close()

    app = FastAPI(
        title="Claude Agent Harness",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.container = container
    app.add_api_route("/healthz", _healthz, methods=["GET"], include_in_schema=False)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=_trace_request)
    app.add_middleware(BaseHTTPMiddleware, dispatch=_authenticate_request)

    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(HarnessDomainError, _domain_error)
    app.add_exception_handler(ManifestValidationError, _manifest_error)
    app.add_exception_handler(AgentPackageCheckError, _agent_package_error)
    app.add_exception_handler(AgentBundleValidationError, _agent_package_error)

    for router in (
        agents.router,
        sessions.router,
        runs.router,
        approvals.router,
        artifacts.router,
        input_artifacts.router,
        agui_routes.router,
    ):
        app.include_router(router, prefix="/v1")
    return app


def create_memory_app(
    *,
    auto_execute: bool = False,
    settings: Settings | None = None,
) -> FastAPI:
    return create_app(
        build_memory_container(auto_execute=auto_execute, settings=settings)
    )


def create_configured_app(settings: Settings) -> FastAPI:
    if settings.environment == "production":
        from harness.composition import build_production_container

        return create_app(
            build_production_container(settings, execution_enabled=False)
        )
    return create_memory_app(
        auto_execute=settings.local_auto_execute,
        settings=settings,
    )


settings = Settings()
app = create_configured_app(settings)
