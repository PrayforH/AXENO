"""FastAPI application factory."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

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


async def _trace_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
    container: ApiContainer = request.app.state.container
    with container.observability.span(
        "harness.api.request",
        attributes={"http.method": request.method, "http.route": request.url.path},
    ):
        return await call_next(request)


def create_app(container: ApiContainer) -> FastAPI:
    app = FastAPI(title="Claude Agent Harness", version="0.1.0")
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=_trace_request)

    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(HarnessDomainError, _domain_error)
    app.add_exception_handler(ManifestValidationError, _manifest_error)

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


settings = Settings()
app = create_memory_app(
    auto_execute=settings.local_auto_execute,
    settings=settings,
)
