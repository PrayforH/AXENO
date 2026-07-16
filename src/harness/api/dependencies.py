"""FastAPI dependencies and the local in-memory composition root."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Header, HTTPException, Request
from pydantic import SecretStr

from harness.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryApprovalRepository,
    InMemoryArtifactRepository,
    InMemoryArtifactStore,
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryInputArtifactRepository,
    InMemoryRunRepository,
    InMemorySessionRepository,
    InMemoryTaskQueue,
    InMemoryThreadFileRepository,
    InMemoryUserMemoryRepository,
    InMemoryWorkspaceSnapshotRepository,
)
from harness.agui.service import AguiRunService
from harness.application.agent_assets import stage_published_agent_assets
from harness.application.agents import AgentService
from harness.application.approvals import ApprovalService
from harness.application.artifacts import ArtifactService
from harness.application.events import EventService
from harness.application.file_catalog import FileCatalogService
from harness.application.input_artifacts import InputArtifactService
from harness.application.memory import UserMemoryService
from harness.application.runs import RunService
from harness.application.sessions import SessionService
from harness.application.workspaces import WorkspacePolicy, WorkspaceService
from harness.auth.audit import AuditService
from harness.auth.repositories import InMemoryAuditRepository, InMemoryAuthRepository
from harness.auth.service import (
    AuthenticationError,
    AuthService,
    OAuthProviderConfig,
)
from harness.config import Settings
from harness.core.errors import NotFoundError
from harness.core.manifest import AgentManifestSnapshot
from harness.core.models import Run, Session
from harness.core.ports import EventRepository, TaskQueue
from harness.evals.controller import EvalController
from harness.evals.queue import EvalTaskQueue
from harness.evals.repositories import (
    EvalDatasetRepository,
    EvalRunRepository,
    InMemoryEvalDatasetRepository,
    InMemoryEvalRunRepository,
)
from harness.evals.service import EvalControlPlaneService
from harness.inputs.processors import DefaultInputProcessor
from harness.observability.provider import Observability, build_observability
from harness.policy.profiles import default_policy_profiles
from harness.policy.rules import PolicyEngine
from harness.runtime.base import AgentRuntime
from harness.runtime.cc_switch import load_cc_switch_claude_config
from harness.runtime.default_tools import (
    default_tool_resolver,
    server_secret_credential_provider,
)
from harness.runtime.fake import FakeRuntime
from harness.runtime.registry_runtime import RegistryClaudeRuntime
from harness.runtime.sdk_tool_gate import SdkToolGate
from harness.sandbox.base import SandboxProvider
from harness.sandbox.daytona import (
    DaytonaSandboxProvider,
    SdkDaytonaClient,
)
from harness.sandbox.local import LocalSandboxProvider
from harness.studio.catalog_repository import InMemoryCapabilityCatalogRepository
from harness.studio.catalog_service import CapabilityCatalogService
from harness.studio.preflight import LivePreflightProvisioner, LivePreflightRunner
from harness.studio.preflight_probes import (
    AnthropicSandboxModelProbe,
    FakeMcpPreflightProbe,
    FakeModelPreflightProbe,
    StreamableHttpMcpProbe,
)
from harness.studio.preview_controller import PreviewController
from harness.studio.preview_queue import PreviewTaskQueue
from harness.studio.preview_repositories import (
    InMemoryPreviewRepository,
    PreviewRepository,
)
from harness.studio.preview_service import PreviewService
from harness.studio.repositories import (
    AgentDraftRepository,
    InMemoryAgentDraftRepository,
)
from harness.studio.service import AgentStudioService
from harness.worker.orchestrator import RunOrchestrator


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    user_id: str
    roles: frozenset[str] = frozenset({"owner"})
    email: str = ""
    display_name: str = ""
    authentication_method: str = "service"


@dataclass(frozen=True)
class ApiContainer:
    environment: str
    api_bearer_token: SecretStr
    auth: AuthService
    audit: AuditService
    agent_drafts: AgentDraftRepository
    capability_catalogs: CapabilityCatalogService
    studio: AgentStudioService
    preview_repository: PreviewRepository
    previews: PreviewService
    preview_controller: PreviewController
    eval_dataset_repository: EvalDatasetRepository
    eval_run_repository: EvalRunRepository
    evals: EvalControlPlaneService
    eval_controller: EvalController
    agents: AgentService
    sessions: SessionService
    runs: RunService
    approvals: ApprovalService
    artifacts: ArtifactService
    input_artifacts: InputArtifactService
    file_catalog: FileCatalogService
    memory: UserMemoryService
    events: EventRepository
    task_queue: TaskQueue
    observability: Observability
    runtime: AgentRuntime
    worker: RunOrchestrator
    agui: AguiRunService
    auto_execute: bool
    close: Callable[[], Awaitable[None]] | None = None


def build_memory_container(
    *,
    auto_execute: bool = False,
    settings: Settings | None = None,
) -> ApiContainer:
    resolved_settings = settings or Settings()
    registry = InMemoryAgentRegistry()
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    approvals = InMemoryApprovalRepository()
    artifact_repository = InMemoryArtifactRepository()
    input_artifact_repository = InMemoryInputArtifactRepository()
    memory_repository = InMemoryUserMemoryRepository()
    thread_file_repository = InMemoryThreadFileRepository()
    workspace_snapshot_repository = InMemoryWorkspaceSnapshotRepository()
    artifact_store = InMemoryArtifactStore()
    events = InMemoryEventRepository()
    bus = InMemoryEventBus()
    queue = InMemoryTaskQueue()
    observability = build_observability(resolved_settings)
    auth = AuthService(
        InMemoryAuthRepository(),
        jwt_secret=resolved_settings.auth_jwt_secret,
        issuer=resolved_settings.auth_issuer,
        audience=resolved_settings.auth_audience,
        access_token_minutes=resolved_settings.auth_access_token_minutes,
        refresh_token_days=resolved_settings.auth_refresh_token_days,
        allow_registration=resolved_settings.auth_allow_registration,
        default_tenant_id=resolved_settings.auth_default_tenant_id,
        google=OAuthProviderConfig(
            resolved_settings.auth_google_client_id,
            resolved_settings.auth_google_client_secret,
        ),
        github=OAuthProviderConfig(
            resolved_settings.auth_github_client_id,
            resolved_settings.auth_github_client_secret,
        ),
    )
    audit = AuditService(InMemoryAuditRepository())
    agent_drafts = InMemoryAgentDraftRepository()
    preview_repository = InMemoryPreviewRepository()
    preview_queue = PreviewTaskQueue.memory()
    eval_dataset_repository = InMemoryEvalDatasetRepository()
    eval_run_repository = InMemoryEvalRunRepository()
    eval_queue = EvalTaskQueue.memory()
    capability_catalog_repository = InMemoryCapabilityCatalogRepository()

    def clock() -> datetime:
        return datetime.now(UTC)

    def id_generator(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"

    agent_service = AgentService(
        registry, clock=clock, environment=resolved_settings.environment
    )
    capability_catalogs = CapabilityCatalogService(
        capability_catalog_repository,
        agent_drafts,
        clock=clock,
    )
    studio_service = AgentStudioService(
        agent_drafts,
        catalogs=capability_catalogs,
        publisher=agent_service,
        registry=registry,
        audit=audit,
        clock=clock,
        id_generator=lambda: id_generator("draft"),
    )
    preview_service = PreviewService(
        repository=preview_repository,
        queue=preview_queue,
        studio=studio_service,
        audit=audit,
        clock=clock,
        id_generator=lambda: id_generator("preview"),
    )
    event_service = EventService(events, bus, clock=clock, id_generator=id_generator)
    run_service = RunService(
        sessions,
        runs,
        queue,
        event_service,
        clock=clock,
        id_generator=id_generator,
        observability=observability,
    )
    session_service = SessionService(
        registry, sessions, clock=clock, id_generator=id_generator
    )
    approval_service = ApprovalService(
        runs=runs,
        approvals=approvals,
        events=event_service,
        clock=clock,
        id_generator=id_generator,
        queue=queue,
    )
    artifact_service = ArtifactService(
        runs=runs,
        repository=artifact_repository,
        store=artifact_store,
        id_generator=id_generator,
        max_file_bytes=resolved_settings.output_artifact_max_bytes,
    )
    file_catalog_service = FileCatalogService(
        thread_file_repository,
        clock=clock,
        id_generator=id_generator,
    )
    input_artifact_service = InputArtifactService(
        repository=input_artifact_repository,
        store=artifact_store,
        id_generator=id_generator,
        clock=clock,
        processor=DefaultInputProcessor(),
        file_catalog=file_catalog_service,
    )
    eval_service = EvalControlPlaneService(
        datasets=eval_dataset_repository,
        runs=eval_run_repository,
        queue=eval_queue,
        studio=studio_service,
        registry=registry,
        object_store=artifact_store,
        previews=preview_service,
        audit=audit,
        clock=clock,
        id_generator=id_generator,
    )
    eval_controller = EvalController(
        datasets=eval_dataset_repository,
        repository=eval_run_repository,
        queue=eval_queue,
        sessions=session_service,
        runs=run_service,
        events=event_service,
        inputs=input_artifact_service,
        object_store=artifact_store,
        clock=clock,
    )
    memory_service = UserMemoryService(memory_repository, clock=clock)
    workspace_service = WorkspaceService(
        artifact_store,
        snapshots=workspace_snapshot_repository,
        max_archive_bytes=resolved_settings.workspace_archive_max_bytes,
        max_archive_members=resolved_settings.workspace_archive_max_members,
    )

    async def workspace_policy_resolver(
        tenant_id: str, agent_name: str, agent_version: str
    ) -> WorkspacePolicy:
        version = await registry.get(tenant_id, agent_name, agent_version)
        manifest = AgentManifestSnapshot.model_validate(version.snapshot).manifest
        return WorkspacePolicy(
            restore_session=manifest.spec.workspace.restore_session,
            archive_on_complete=manifest.spec.workspace.archive_on_complete,
        )

    async def stage_runtime_assets(
        tenant_id: str,
        agent_name: str,
        agent_version: str,
        workspace: Path,
    ) -> tuple[str, ...]:
        return await stage_published_agent_assets(
            registry,
            tenant_id=tenant_id,
            agent_name=agent_name,
            agent_version=agent_version,
            workspace=workspace,
        )

    policy_profiles = default_policy_profiles()

    async def resolve_policy(
        tenant_id: str, agent_name: str, agent_version: str
    ) -> PolicyEngine:
        version = await registry.get(tenant_id, agent_name, agent_version)
        manifest = AgentManifestSnapshot.model_validate(version.snapshot).manifest
        return policy_profiles.resolve(manifest.spec.permissions.policy)

    policy = policy_profiles.resolve("local-standard")
    if resolved_settings.sandbox_provider == "daytona":
        daytona_api_key = resolved_settings.daytona_api_key.get_secret_value()
        if not daytona_api_key:
            raise ValueError("HARNESS_DAYTONA_API_KEY is required for Daytona")
        sandbox: SandboxProvider = DaytonaSandboxProvider(
            client=SdkDaytonaClient.from_config(
                api_key=daytona_api_key,
                api_url=resolved_settings.daytona_api_url or None,
                target=resolved_settings.daytona_target or None,
            ),
            snapshot=resolved_settings.daytona_snapshot or None,
            remote_workspace_root=resolved_settings.daytona_remote_workspace_root,
            cli_version=resolved_settings.daytona_claude_cli_version,
            cli_path=resolved_settings.daytona_claude_cli_path,
            delete_on_destroy=resolved_settings.daytona_delete_on_destroy,
            auto_stop_interval_minutes=(
                resolved_settings.daytona_auto_stop_interval_minutes
            ),
            auto_delete_interval_minutes=(
                resolved_settings.daytona_auto_delete_interval_minutes
            ),
            max_collect_bytes=resolved_settings.workspace_archive_max_bytes,
            max_collect_members=resolved_settings.workspace_archive_max_members,
        )
    else:
        sandbox = LocalSandboxProvider()
    if resolved_settings.runtime == "fake":
        runtime: AgentRuntime = FakeRuntime()
        model_probe = FakeModelPreflightProbe()
        mcp_probe = FakeMcpPreflightProbe()
    else:
        credential_provider = server_secret_credential_provider(
            references_json=resolved_settings.mcp_secret_references_json,
            secrets_json=resolved_settings.mcp_server_secrets_json.get_secret_value(),
        )
        gateway = load_cc_switch_claude_config(
            resolved_settings.cc_switch_settings_path
        )
        tool_resolver = default_tool_resolver(credential_provider)
        runtime = RegistryClaudeRuntime(
            registry=registry,
            config=gateway,
            tool_resolver=tool_resolver,
            tool_gate=SdkToolGate(
                profiles=policy_profiles,
                approvals=approval_service,
                events=event_service,
            ),
            memory_service=memory_service,
            observability=observability,
        )
        model_probe = AnthropicSandboxModelProbe(gateway)
        mcp_probe = StreamableHttpMcpProbe(tool_resolver)
    preflight_runner = LivePreflightRunner(
        studio=studio_service,
        sandbox=sandbox,
        model_probe=model_probe,
        mcp_probe=mcp_probe,
        policies=policy_profiles,
        observability=observability,
        timeout_seconds=resolved_settings.preflight_timeout_seconds,
        clock=clock,
    )
    preview_controller = PreviewController(
        repository=preview_repository,
        queue=preview_queue,
        provisioner=LivePreflightProvisioner(
            runner=preflight_runner,
            repository=preview_repository,
            clock=clock,
        ),
        heartbeat_seconds=resolved_settings.worker_task_heartbeat_seconds,
        clock=clock,
    )
    worker = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=event_service,
        runtime=runtime,
        sandbox=sandbox,
        clock=clock,
        policy=policy,
        approvals=approval_service,
        workspaces=workspace_service,
        observability=observability,
        artifacts=artifact_service,
        input_artifacts=input_artifact_service,
        memory=memory_service,
        workspace_policy_resolver=workspace_policy_resolver,
        runtime_asset_stager=(
            stage_runtime_assets
            if resolved_settings.runtime == "claude-sdk"
            else None
        ),
        policy_resolver=resolve_policy,
        output_artifact_max_bytes=resolved_settings.output_artifact_max_bytes,
    )
    agui = AguiRunService(
        sessions=session_service,
        runs=run_service,
        input_artifacts=input_artifact_service,
    )
    return ApiContainer(
        environment=resolved_settings.environment,
        api_bearer_token=resolved_settings.api_bearer_token,
        auth=auth,
        audit=audit,
        agent_drafts=agent_drafts,
        capability_catalogs=capability_catalogs,
        studio=studio_service,
        preview_repository=preview_repository,
        previews=preview_service,
        preview_controller=preview_controller,
        eval_dataset_repository=eval_dataset_repository,
        eval_run_repository=eval_run_repository,
        evals=eval_service,
        eval_controller=eval_controller,
        agents=agent_service,
        sessions=session_service,
        runs=run_service,
        approvals=approval_service,
        artifacts=artifact_service,
        input_artifacts=input_artifact_service,
        file_catalog=file_catalog_service,
        memory=memory_service,
        events=events,
        task_queue=queue,
        observability=observability,
        runtime=runtime,
        worker=worker,
        agui=agui,
        auto_execute=auto_execute,
    )


def get_container(request: Request) -> ApiContainer:
    return request.app.state.container


async def require_identity(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
) -> Identity:
    container: ApiContainer = request.app.state.container
    scheme, separator, credential = (authorization or "").partition(" ")
    service_authenticated = bool(
        getattr(request.state, "service_authenticated", False)
    )
    if separator and scheme.lower() == "bearer" and credential.count(".") == 2:
        try:
            claims = container.auth.authenticate_access_token(credential)
            user, membership = await container.auth.current_user(claims)
        except AuthenticationError as error:
            raise HTTPException(
                status_code=401,
                detail={"code": "access_token_invalid", "message": str(error)},
                headers={"WWW-Authenticate": "Bearer"},
            ) from error
        identity = Identity(
            tenant_id=membership.tenant_id,
            user_id=user.user_id,
            roles=frozenset({membership.role}),
            email=user.email,
            display_name=user.display_name,
            authentication_method="jwt",
        )
        request.state.identity = identity
        return identity
    legacy_allowed = service_authenticated or container.environment != "production"
    if not legacy_allowed or not tenant_id or not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "identity_required",
                "message": "Sign in with a valid access token",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    identity = Identity(tenant_id=tenant_id, user_id=user_id)
    request.state.identity = identity
    return identity


_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset({"*"}),
    "admin": frozenset(
        {
            "agents:publish",
            "tasks:read",
            "tasks:write",
            "audit:read",
            "studio:read",
            "studio:write",
            "studio:preview",
            "studio:publish",
            "studio:deploy",
            "studio:catalog:write",
        }
    ),
    "member": frozenset(
        {
            "tasks:read",
            "tasks:write",
            "studio:read",
            "studio:write",
            "studio:preview",
        }
    ),
    "viewer": frozenset({"tasks:read", "studio:read"}),
}


def ensure_permission(identity: Identity, permission: str) -> None:
    granted: set[str] = set()
    for role in identity.roles:
        granted.update(_ROLE_PERMISSIONS.get(role, frozenset()))
    if "*" not in granted and permission not in granted:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "permission_denied",
                "message": f"Permission required: {permission}",
            },
        )


async def require_owned_session(
    container: ApiContainer, identity: Identity, session_id: str
) -> Session:
    session = await container.sessions.get(identity.tenant_id, session_id)
    if session.user_id != identity.user_id:
        raise NotFoundError(f"session not found: {session_id}")
    return session


async def require_owned_run(
    container: ApiContainer, identity: Identity, run_id: str
) -> Run:
    run = await container.runs.get(identity.tenant_id, run_id)
    await require_owned_session(container, identity, run.session_id)
    return run
