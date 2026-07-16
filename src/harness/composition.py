"""Production composition root using PostgreSQL, Redis, MinIO and Claude SDK."""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import SecretStr
from redis.asyncio import Redis

from harness.agui.service import AguiRunService
from harness.agui.task_title import AnthropicCompatibleTaskTitleGenerator
from harness.api.dependencies import ApiContainer
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
from harness.auth.repositories import PostgresAuditRepository, PostgresAuthRepository
from harness.auth.service import AuthService, OAuthProviderConfig
from harness.config import Settings
from harness.core.manifest import AgentManifestSnapshot
from harness.core.models import ModelCompatibility, Session
from harness.core.ports import ArtifactStore, TaskQueue
from harness.deployments.controller import DeploymentController
from harness.deployments.queue import DeploymentTaskQueue
from harness.deployments.service import DeploymentService
from harness.evals.controller import EvalController
from harness.evals.queue import EvalTaskQueue
from harness.evals.service import EvalControlPlaneService
from harness.execution.credentials import (
    BrokerMcpCredentialProvider,
    CredentialResourceKind,
    CredentialSourceKey,
    InMemoryCredentialBroker,
)
from harness.inputs.processors import DefaultInputProcessor
from harness.observability.provider import build_observability
from harness.policy.profiles import default_policy_profiles
from harness.policy.rules import PolicyEngine
from harness.quality.controller import QualitySyncController
from harness.quality.langfuse import DisabledQualityExporter, LangfuseQualityExporter
from harness.quality.queue import QualityTaskQueue
from harness.quality.service import QualityService
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.runtime.default_tools import (
    default_tool_resolver,
)
from harness.runtime.fake import FakeRuntime
from harness.runtime.mcp_credentials import DynamicMcpCredentialProvider
from harness.runtime.registry_runtime import RegistryClaudeRuntime
from harness.runtime.sdk_tool_gate import SdkToolGate
from harness.runtime.session_store import PostgresSessionStore
from harness.sandbox.base import SandboxProvider
from harness.sandbox.daytona import DaytonaSandboxProvider, SdkDaytonaClient
from harness.sandbox.kubernetes import (
    KubectlKubernetesClient,
    KubernetesSandboxProvider,
)
from harness.sandbox.local import LocalSandboxProvider
from harness.storage.catalog_repository import PostgresCapabilityCatalogRepository
from harness.storage.database import create_database
from harness.storage.deployment_repository import (
    PostgresDeploymentRepository,
    PostgresEnvironmentRepository,
)
from harness.storage.eval_repository import (
    PostgresEvalDatasetRepository,
    PostgresEvalRunRepository,
)
from harness.storage.minio import MinioArtifactStore
from harness.storage.platform_repositories import (
    PostgresAgentRegistry,
    PostgresAguiThreadBindingRepository,
    PostgresApprovalRepository,
    PostgresArtifactRepository,
    PostgresInputArtifactRepository,
    PostgresSessionRepository,
    PostgresThreadFileRepository,
    PostgresUserMemoryRepository,
    PostgresWorkspaceSnapshotRepository,
)
from harness.storage.preview_repository import PostgresPreviewRepository
from harness.storage.quality_repository import PostgresQualityRepository
from harness.storage.redis import AsyncRedisClient, RedisEventBus, RedisTaskQueue
from harness.storage.repositories import PostgresEventRepository, PostgresRunRepository
from harness.storage.studio_repository import PostgresAgentDraftRepository
from harness.studio.catalog import default_capability_catalog
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
from harness.studio.preview_service import PreviewService
from harness.studio.service import AgentStudioService
from harness.worker.orchestrator import RunOrchestrator, SandboxResolver


def _gateway_capabilities(value: str) -> frozenset[str]:
    capabilities = frozenset(part.strip() for part in value.split(",") if part.strip())
    if not capabilities:
        raise ValueError("HARNESS_NEW_API_CAPABILITIES must not be empty")
    return capabilities


def _anthropic_gateway(settings: Settings) -> CcSwitchClaudeConfig | None:
    anthropic_key = settings.anthropic_api_key.get_secret_value()
    if not (settings.anthropic_base_url and settings.anthropic_model and anthropic_key):
        return None
    return CcSwitchClaudeConfig(
        base_url=settings.anthropic_base_url,
        model=settings.anthropic_model,
        provider="anthropic",
        credential=SecretStr(anthropic_key),
        compatibility=ModelCompatibility.FULL,
        capabilities=frozenset({"streaming", "tool_use"}),
    )


def _gateways(
    settings: Settings,
) -> tuple[CcSwitchClaudeConfig, CcSwitchClaudeConfig | None]:
    new_api_key = settings.new_api_key.get_secret_value()
    if settings.new_api_base_url and settings.new_api_model and new_api_key:
        return (
            CcSwitchClaudeConfig(
                base_url=settings.new_api_base_url,
                model=settings.new_api_model,
                provider="new-api",
                credential=SecretStr(new_api_key),
                compatibility=ModelCompatibility(settings.new_api_compatibility),
                capabilities=_gateway_capabilities(settings.new_api_capabilities),
            ),
            _anthropic_gateway(settings),
        )
    anthropic = _anthropic_gateway(settings)
    if anthropic is not None:
        return anthropic, None
    raise ValueError(
        "production requires HARNESS_NEW_API_BASE_URL/MODEL/KEY or "
        "HARNESS_ANTHROPIC_BASE_URL/MODEL/API_KEY"
    )


def _sandbox(settings: Settings) -> SandboxProvider:
    if settings.sandbox_provider == "local":
        if not settings.allow_unsafe_local_sandbox:
            raise ValueError(
                "production local sandbox requires "
                "HARNESS_ALLOW_UNSAFE_LOCAL_SANDBOX=true; use Daytona for untrusted Agents"
            )
        return LocalSandboxProvider()
    if settings.sandbox_provider == "kubernetes":
        if not settings.kubernetes_image:
            raise ValueError("HARNESS_KUBERNETES_IMAGE is required for Kubernetes")
        try:
            selector_raw = json.loads(
                settings.kubernetes_egress_gateway_selector_json
            )
        except json.JSONDecodeError:
            raise ValueError(
                "HARNESS_KUBERNETES_EGRESS_GATEWAY_SELECTOR_JSON must be JSON"
            ) from None
        if not isinstance(selector_raw, dict):
            raise ValueError("Kubernetes egress gateway selector must map strings")
        selector_items = cast(dict[object, object], selector_raw)
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in selector_items.items()
        ):
            raise ValueError("Kubernetes egress gateway selector must map strings")
        if not settings.kubernetes_egress_proxy_url:
            raise ValueError(
                "HARNESS_KUBERNETES_EGRESS_PROXY_URL is required for Kubernetes"
            )
        client = KubectlKubernetesClient(
            namespace=settings.kubernetes_namespace,
            kubectl_path=settings.kubernetes_kubectl_path,
            kubeconfig=settings.kubernetes_kubeconfig or None,
            context=settings.kubernetes_context or None,
        )
        return KubernetesSandboxProvider(
            client=client,
            namespace=settings.kubernetes_namespace,
            image=settings.kubernetes_image,
            runtime_class_name=settings.kubernetes_runtime_class_name,
            service_account_name=settings.kubernetes_service_account_name,
            remote_workspace=settings.kubernetes_remote_workspace,
            cli_version=settings.kubernetes_claude_cli_version,
            cli_path=settings.kubernetes_claude_cli_path,
            ttl_seconds=settings.kubernetes_pod_ttl_seconds,
            ready_timeout_seconds=settings.kubernetes_ready_timeout_seconds,
            cpu_millis=settings.kubernetes_cpu_millis,
            memory_mib=settings.kubernetes_memory_mib,
            disk_mib=settings.kubernetes_disk_mib,
            egress_gateway_namespace=settings.kubernetes_egress_gateway_namespace,
            egress_gateway_selector=cast(dict[str, str], selector_items),
            egress_gateway_port=settings.kubernetes_egress_gateway_port,
            egress_proxy_url=settings.kubernetes_egress_proxy_url,
            dns_namespace=settings.kubernetes_dns_namespace,
            max_collect_bytes=settings.workspace_archive_max_bytes,
            max_collect_members=settings.workspace_archive_max_members,
        )
    api_key = settings.daytona_api_key.get_secret_value()
    if not api_key:
        raise ValueError("HARNESS_DAYTONA_API_KEY is required for Daytona")
    return DaytonaSandboxProvider(
        client=SdkDaytonaClient.from_config(
            api_key=api_key,
            api_url=settings.daytona_api_url or None,
            target=settings.daytona_target or None,
        ),
        snapshot=settings.daytona_snapshot or None,
        remote_workspace_root=settings.daytona_remote_workspace_root,
        cli_version=settings.daytona_claude_cli_version,
        cli_path=settings.daytona_claude_cli_path,
        delete_on_destroy=settings.daytona_delete_on_destroy,
        auto_stop_interval_minutes=settings.daytona_auto_stop_interval_minutes,
        auto_delete_interval_minutes=settings.daytona_auto_delete_interval_minutes,
        max_collect_bytes=settings.workspace_archive_max_bytes,
        max_collect_members=settings.workspace_archive_max_members,
    )


def build_production_container(
    settings: Settings, *, execution_enabled: bool = True
) -> ApiContainer:
    if settings.environment != "production":
        raise ValueError("production composition requires HARNESS_ENVIRONMENT=production")
    if settings.runtime != "claude-sdk":
        raise ValueError("production composition requires HARNESS_RUNTIME=claude-sdk")
    access_key = settings.minio_access_key.get_secret_value()
    secret_key = settings.minio_secret_key.get_secret_value()
    if not access_key or not secret_key:
        raise ValueError("production requires HARNESS_MINIO_ACCESS_KEY and SECRET_KEY")
    execution_config: (
        tuple[
            CcSwitchClaudeConfig,
            CcSwitchClaudeConfig | None,
            SandboxProvider,
            DynamicMcpCredentialProvider,
            InMemoryCredentialBroker,
        ]
        | None
    ) = None
    sandbox_maintenance: Callable[[], Awaitable[object]] | None = None
    credential_broker: InMemoryCredentialBroker | None = None
    try:
        title_gateway, _ = _gateways(settings)
    except ValueError:
        title_gateway = None
    if execution_enabled:
        primary_gateway, fallback_gateway = _gateways(settings)
        sandbox = _sandbox(settings)
        if isinstance(sandbox, KubernetesSandboxProvider):
            sandbox_maintenance = sandbox.reap_expired
        references_raw = json.loads(settings.mcp_secret_references_json)
        secrets_raw = json.loads(settings.mcp_server_secrets_json.get_secret_value())
        if not isinstance(references_raw, dict) or not isinstance(secrets_raw, dict):
            raise ValueError("MCP credential settings must be JSON objects")
        typed_secrets = cast(dict[object, object], secrets_raw)
        sources: dict[
            CredentialSourceKey, tuple[str, dict[str, SecretStr]]
        ] = {
            ("*", CredentialResourceKind.MODEL, "new-api-default"): (
                f"settings://{primary_gateway.provider}/primary",
                {"api_key": primary_gateway.credential},
            ),
            ("*", CredentialResourceKind.MODEL, "anthropic-official"): (
                f"settings://{(fallback_gateway or primary_gateway).provider}/fallback",
                {"api_key": (fallback_gateway or primary_gateway).credential},
            ),
        }
        for server, raw_references in cast(dict[object, object], references_raw).items():
            if not isinstance(raw_references, dict):
                continue
            values = {
                str(key): SecretStr(str(typed_secrets[secret_reference]))
                for key, secret_reference in cast(
                    dict[object, object], raw_references
                ).items()
                if secret_reference in typed_secrets
            }
            sources[("*", CredentialResourceKind.MCP, str(server))] = (
                f"settings://mcp/{server}",
                values,
            )
        credential_broker = InMemoryCredentialBroker(
            sources,
            clock=lambda: datetime.now(UTC),
        )
        credential_provider = BrokerMcpCredentialProvider(credential_broker)
        execution_config = (
            primary_gateway,
            fallback_gateway,
            sandbox,
            credential_provider,
            credential_broker,
        )

    engine, sessions = create_database(settings.database_url)
    redis = Redis.from_url(settings.redis_url)  # pyright: ignore[reportUnknownMemberType]
    redis_client = cast(AsyncRedisClient, redis)
    registry = PostgresAgentRegistry(sessions)
    session_repository = PostgresSessionRepository(sessions)
    runs = PostgresRunRepository(sessions)
    approvals = PostgresApprovalRepository(sessions)
    artifact_repository = PostgresArtifactRepository(sessions)
    input_repository = PostgresInputArtifactRepository(sessions)
    memory_repository = PostgresUserMemoryRepository(sessions)
    file_repository = PostgresThreadFileRepository(sessions)
    snapshot_repository = PostgresWorkspaceSnapshotRepository(sessions)
    binding_repository = PostgresAguiThreadBindingRepository(sessions)
    event_repository = PostgresEventRepository(sessions)
    agent_drafts = PostgresAgentDraftRepository(sessions)
    preview_repository = PostgresPreviewRepository(sessions)
    eval_dataset_repository = PostgresEvalDatasetRepository(sessions)
    eval_run_repository = PostgresEvalRunRepository(sessions)
    environment_repository = PostgresEnvironmentRepository(sessions)
    deployment_repository = PostgresDeploymentRepository(sessions)
    quality_repository = PostgresQualityRepository(sessions)
    capability_catalog_repository = PostgresCapabilityCatalogRepository(sessions)
    auth = AuthService(
        PostgresAuthRepository(sessions),
        jwt_secret=settings.auth_jwt_secret,
        issuer=settings.auth_issuer,
        audience=settings.auth_audience,
        access_token_minutes=settings.auth_access_token_minutes,
        refresh_token_days=settings.auth_refresh_token_days,
        allow_registration=settings.auth_allow_registration,
        default_tenant_id=settings.auth_default_tenant_id,
        google=OAuthProviderConfig(
            settings.auth_google_client_id, settings.auth_google_client_secret
        ),
        github=OAuthProviderConfig(
            settings.auth_github_client_id, settings.auth_github_client_secret
        ),
    )
    audit = AuditService(PostgresAuditRepository(sessions))
    if settings.worker_task_heartbeat_seconds >= settings.worker_task_visibility_timeout_seconds:
        raise ValueError("worker task heartbeat must be shorter than visibility timeout")
    queue: TaskQueue = RedisTaskQueue(
        redis_client,
        visibility_timeout_seconds=settings.worker_task_visibility_timeout_seconds,
        retry_delay_seconds=settings.worker_task_retry_delay_seconds,
    )
    bus = RedisEventBus(redis_client)
    store: ArtifactStore = MinioArtifactStore(
        endpoint=settings.minio_endpoint,
        access_key=access_key,
        secret_key=secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    observability = build_observability(settings)

    def clock() -> datetime:
        return datetime.now(UTC)

    def ids(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"

    agent_service = AgentService(registry, clock=clock, environment="production")
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
        id_generator=lambda: ids("draft"),
    )
    preview_queue = PreviewTaskQueue.redis(
        redis_client,
        visibility_timeout_seconds=settings.worker_task_visibility_timeout_seconds,
        retry_delay_seconds=settings.worker_task_retry_delay_seconds,
    )
    eval_queue = EvalTaskQueue.redis(
        redis_client,
        visibility_timeout_seconds=settings.worker_task_visibility_timeout_seconds,
        retry_delay_seconds=settings.worker_task_retry_delay_seconds,
    )
    deployment_queue = DeploymentTaskQueue.redis(
        redis_client,
        visibility_timeout_seconds=settings.worker_task_visibility_timeout_seconds,
        retry_delay_seconds=settings.worker_task_retry_delay_seconds,
    )
    quality_queue = QualityTaskQueue.redis(
        redis_client,
        visibility_timeout_seconds=settings.worker_task_visibility_timeout_seconds,
        retry_delay_seconds=settings.worker_task_retry_delay_seconds,
    )
    preview_service = PreviewService(
        repository=preview_repository,
        queue=preview_queue,
        studio=studio_service,
        audit=audit,
        clock=clock,
        id_generator=lambda: ids("preview"),
    )
    events = EventService(event_repository, bus, clock=clock, id_generator=ids)
    session_service = SessionService(
        registry,
        session_repository,
        clock=clock,
        id_generator=ids,
        require_published_dependencies=True,
    )
    run_service = RunService(
        session_repository,
        runs,
        queue,
        events,
        clock=clock,
        id_generator=ids,
        observability=observability,
    )
    approval_service = ApprovalService(
        runs=runs,
        approvals=approvals,
        events=events,
        clock=clock,
        id_generator=ids,
        queue=queue,
    )
    artifact_service = ArtifactService(
        runs=runs,
        repository=artifact_repository,
        store=store,
        id_generator=ids,
        max_file_bytes=settings.output_artifact_max_bytes,
    )
    file_service = FileCatalogService(file_repository, clock=clock, id_generator=ids)
    input_service = InputArtifactService(
        repository=input_repository,
        store=store,
        id_generator=ids,
        clock=clock,
        processor=DefaultInputProcessor(),
        file_catalog=file_service,
    )
    eval_service = EvalControlPlaneService(
        datasets=eval_dataset_repository,
        runs=eval_run_repository,
        queue=eval_queue,
        studio=studio_service,
        registry=registry,
        object_store=store,
        previews=preview_service,
        audit=audit,
        clock=clock,
        id_generator=ids,
    )
    eval_controller = EvalController(
        datasets=eval_dataset_repository,
        repository=eval_run_repository,
        queue=eval_queue,
        sessions=session_service,
        runs=run_service,
        events=events,
        inputs=input_service,
        object_store=store,
        clock=clock,
    )
    quality_service = QualityService(
        repository=quality_repository,
        queue=quality_queue,
        runs=runs,
        sessions=session_repository,
        events=event_repository,
        artifacts=artifact_repository,
        clock=clock,
    )
    quality_exporter = (
        LangfuseQualityExporter(
            base_url=settings.langfuse_base_url,
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
        )
        if settings.langfuse_base_url
        and settings.langfuse_public_key
        and settings.langfuse_secret_key.get_secret_value()
        else DisabledQualityExporter()
    )
    quality_controller = QualitySyncController(
        repository=quality_repository,
        queue=quality_queue,
        exporter=quality_exporter,
    )
    deployment_service = DeploymentService(
        environments=environment_repository,
        deployments=deployment_repository,
        queue=deployment_queue,
        registry=registry,
        evals=eval_service,
        previews=preview_service,
        audit=audit,
        clock=clock,
        id_generator=ids,
        quality_gate=quality_service.require_promotion_allowed,
    )
    session_service.configure_deployment_resolver(deployment_service.resolve)
    deployment_controller = DeploymentController(
        environments=environment_repository,
        deployments=deployment_repository,
        queue=deployment_queue,
        clock=clock,
    )
    memory_service = UserMemoryService(memory_repository, clock=clock)
    workspace_service = WorkspaceService(
        store,
        snapshots=snapshot_repository,
        max_archive_bytes=settings.workspace_archive_max_bytes,
        max_archive_members=settings.workspace_archive_max_members,
    )

    async def workspace_policy(
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

    async def resolve_policy(tenant_id: str, agent_name: str, agent_version: str) -> PolicyEngine:
        version = await registry.get(tenant_id, agent_name, agent_version)
        manifest = AgentManifestSnapshot.model_validate(version.snapshot).manifest
        return policy_profiles.resolve(manifest.spec.permissions.policy)

    policy = policy_profiles.resolve("local-standard")
    sandbox_resolver: SandboxResolver | None = None
    if execution_enabled:
        assert execution_config is not None
        (
            primary_gateway,
            fallback_gateway,
            runtime_sandbox,
            credential_provider,
            credential_broker,
        ) = execution_config
        tool_resolver = default_tool_resolver(credential_provider)
        runtime = RegistryClaudeRuntime(
            registry=registry,
            config=primary_gateway,
            fallback_config=fallback_gateway,
            tool_resolver=tool_resolver,
            tool_gate=SdkToolGate(
                profiles=policy_profiles,
                approvals=approval_service,
                events=events,
            ),
            memory_service=memory_service,
            session_store_factory=lambda session: PostgresSessionStore(
                sessions,
                tenant_id=session.tenant_id,
                project_id=session.session_id,
            ),
            observability=observability,
            credential_broker=credential_broker,
        )
        model_probe = AnthropicSandboxModelProbe(primary_gateway)
        mcp_probe = StreamableHttpMcpProbe(tool_resolver)

        async def resolve_runtime_sandbox(
            tenant_id: str, session: Session
        ) -> SandboxProvider:
            if session.deployment_snapshot_id is None:
                return runtime_sandbox
            snapshot = await deployment_repository.get_snapshot(
                tenant_id, session.deployment_snapshot_id
            )
            profile = next(
                (
                    item
                    for item in default_capability_catalog().execution_profiles
                    if item.profile_id == snapshot.execution_profile
                    and item.version == snapshot.execution_profile_version
                ),
                None,
            )
            if profile is None:
                raise RuntimeError("deployment_execution_profile_unavailable")
            actual = (
                "gvisor"
                if isinstance(runtime_sandbox, KubernetesSandboxProvider)
                else "daytona"
                if isinstance(runtime_sandbox, DaytonaSandboxProvider)
                else "local"
            )
            if profile.sandbox_provider != actual:
                raise RuntimeError("execution_profile_sandbox_provider_mismatch")
            return runtime_sandbox

        sandbox_resolver = resolve_runtime_sandbox
    else:
        runtime = FakeRuntime()
        runtime_sandbox = LocalSandboxProvider()
        model_probe = FakeModelPreflightProbe()
        mcp_probe = FakeMcpPreflightProbe()
    preflight_runner = LivePreflightRunner(
        studio=studio_service,
        sandbox=runtime_sandbox,
        model_probe=model_probe,
        mcp_probe=mcp_probe,
        policies=policy_profiles,
        observability=observability,
        timeout_seconds=settings.preflight_timeout_seconds,
        clock=clock,
        enforce_execution_profile_provider=True,
    )
    preview_controller = PreviewController(
        repository=preview_repository,
        queue=preview_queue,
        provisioner=LivePreflightProvisioner(
            runner=preflight_runner,
            repository=preview_repository,
            clock=clock,
        ),
        heartbeat_seconds=settings.worker_task_heartbeat_seconds,
        clock=clock,
    )
    worker = RunOrchestrator(
        sessions=session_repository,
        runs=runs,
        events=events,
        runtime=runtime,
        sandbox=runtime_sandbox,
        clock=clock,
        policy=policy,
        approvals=approval_service,
        workspaces=workspace_service,
        observability=observability,
        artifacts=artifact_service,
        input_artifacts=input_service,
        memory=memory_service,
        workspace_policy_resolver=workspace_policy,
        runtime_asset_stager=stage_runtime_assets if execution_enabled else None,
        policy_resolver=resolve_policy,
        output_artifact_max_bytes=settings.output_artifact_max_bytes,
        quality_hook=quality_service.record_terminal_run,
        credential_revoker=(
            credential_broker.revoke_run if credential_broker is not None else None
        ),
        sandbox_resolver=sandbox_resolver,
    )
    agui = AguiRunService(
        sessions=session_service,
        runs=run_service,
        input_artifacts=input_service,
        bindings=binding_repository,
        title_generator=(
            AnthropicCompatibleTaskTitleGenerator(
                base_url=title_gateway.base_url,
                model=title_gateway.model,
                credential=title_gateway.credential,
                provider=title_gateway.provider,
            )
            if title_gateway is not None
            else None
        ),
    )

    async def close() -> None:
        await redis.aclose()
        await engine.dispose()

    return ApiContainer(
        environment="production",
        api_bearer_token=settings.api_bearer_token,
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
        environment_repository=environment_repository,
        deployment_repository=deployment_repository,
        deployments=deployment_service,
        deployment_controller=deployment_controller,
        quality_repository=quality_repository,
        quality=quality_service,
        quality_controller=quality_controller,
        agents=agent_service,
        sessions=session_service,
        runs=run_service,
        approvals=approval_service,
        artifacts=artifact_service,
        input_artifacts=input_service,
        file_catalog=file_service,
        memory=memory_service,
        events=event_repository,
        task_queue=queue,
        observability=observability,
        runtime=runtime,
        worker=worker,
        agui=agui,
        auto_execute=False,
        sandbox_maintenance=sandbox_maintenance,
        close=close,
    )
