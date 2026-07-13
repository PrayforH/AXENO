"""Production composition root using PostgreSQL, Redis, MinIO and Claude SDK."""

import json
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from pydantic import SecretStr
from redis.asyncio import Redis

from harness.agui.service import AguiRunService
from harness.api.dependencies import ApiContainer
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
from harness.config import Settings
from harness.core.manifest import AgentManifestSnapshot
from harness.core.ports import ArtifactStore, TaskQueue
from harness.inputs.processors import DefaultInputProcessor
from harness.observability.provider import build_observability
from harness.policy.rules import PolicyEngine, default_policy_rules
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.runtime.mcp_credentials import ServerSecretReferenceProvider
from harness.runtime.registry_runtime import RegistryClaudeRuntime
from harness.runtime.sdk_tool_gate import SdkToolGate
from harness.runtime.session_store import PostgresSessionStore
from harness.sandbox.base import SandboxProvider
from harness.sandbox.daytona import DaytonaSandboxProvider, SdkDaytonaClient
from harness.sandbox.local import LocalSandboxProvider
from harness.storage.database import create_database
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
from harness.storage.redis import AsyncRedisClient, RedisEventBus, RedisTaskQueue
from harness.storage.repositories import PostgresEventRepository, PostgresRunRepository
from harness.worker.orchestrator import RunOrchestrator


def _gateway(settings: Settings) -> CcSwitchClaudeConfig:
    new_api_key = settings.new_api_key.get_secret_value()
    if settings.new_api_base_url and settings.new_api_model and new_api_key:
        return CcSwitchClaudeConfig(
            base_url=settings.new_api_base_url,
            model=settings.new_api_model,
            provider="new-api",
            credential=SecretStr(new_api_key),
        )
    anthropic_key = settings.anthropic_api_key.get_secret_value()
    if settings.anthropic_base_url and settings.anthropic_model and anthropic_key:
        return CcSwitchClaudeConfig(
            base_url=settings.anthropic_base_url,
            model=settings.anthropic_model,
            provider="anthropic",
            credential=SecretStr(anthropic_key),
        )
    raise ValueError(
        "production requires HARNESS_NEW_API_BASE_URL/MODEL/KEY or "
        "HARNESS_ANTHROPIC_BASE_URL/MODEL/API_KEY"
    )


def _sandbox(settings: Settings) -> SandboxProvider:
    if settings.sandbox_provider == "local":
        return LocalSandboxProvider()
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
        delete_on_destroy=settings.daytona_delete_on_destroy,
    )


def _credential_provider(settings: Settings) -> ServerSecretReferenceProvider:
    references_raw: object = json.loads(settings.mcp_secret_references_json)
    secrets_raw: object = json.loads(settings.mcp_server_secrets_json.get_secret_value())
    if not isinstance(references_raw, dict) or not isinstance(secrets_raw, dict):
        raise ValueError("MCP credential settings must be JSON objects")
    references: dict[str, dict[str, str]] = {}
    for server, raw_values in cast(dict[object, object], references_raw).items():
        if not isinstance(raw_values, dict):
            continue
        values = cast(dict[object, object], raw_values)
        references[str(server)] = {
            str(key): str(value) for key, value in values.items()
        }
    secrets = {
        str(key): SecretStr(str(value))
        for key, value in cast(dict[object, object], secrets_raw).items()
    }
    return ServerSecretReferenceProvider(references=references, secrets=secrets)


def build_production_container(settings: Settings) -> ApiContainer:
    if settings.environment != "production":
        raise ValueError("production composition requires HARNESS_ENVIRONMENT=production")
    if settings.runtime != "claude-sdk":
        raise ValueError("production composition requires HARNESS_RUNTIME=claude-sdk")
    access_key = settings.minio_access_key.get_secret_value()
    secret_key = settings.minio_secret_key.get_secret_value()
    if not access_key or not secret_key:
        raise ValueError("production requires HARNESS_MINIO_ACCESS_KEY and SECRET_KEY")

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
    queue: TaskQueue = RedisTaskQueue(redis_client)
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

    events = EventService(event_repository, bus, clock=clock, id_generator=ids)
    session_service = SessionService(registry, session_repository, clock=clock, id_generator=ids)
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
    )
    artifact_service = ArtifactService(
        runs=runs, repository=artifact_repository, store=store, id_generator=ids
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
    memory_service = UserMemoryService(memory_repository, clock=clock)
    workspace_service = WorkspaceService(store, snapshots=snapshot_repository)

    async def workspace_policy(
        tenant_id: str, agent_name: str, agent_version: str
    ) -> WorkspacePolicy:
        version = await registry.get(tenant_id, agent_name, agent_version)
        manifest = AgentManifestSnapshot.model_validate(version.snapshot).manifest
        return WorkspacePolicy(
            restore_session=manifest.spec.workspace.restore_session,
            archive_on_complete=manifest.spec.workspace.archive_on_complete,
        )

    policy = PolicyEngine(default_policy_rules())
    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=_gateway(settings),
        mcp_credential_provider=_credential_provider(settings),
        tool_gate=SdkToolGate(
            policy=policy, approvals=approval_service, events=events
        ),
        memory_service=memory_service,
        session_store_factory=lambda tenant_id: PostgresSessionStore(
            sessions, tenant_id=tenant_id
        ),
        observability=observability,
    )
    worker = RunOrchestrator(
        sessions=session_repository,
        runs=runs,
        events=events,
        runtime=runtime,
        sandbox=_sandbox(settings),
        clock=clock,
        policy=policy,
        approvals=approval_service,
        workspaces=workspace_service,
        observability=observability,
        artifacts=artifact_service,
        input_artifacts=input_service,
        memory=memory_service,
        workspace_policy_resolver=workspace_policy,
        output_artifact_max_bytes=settings.output_artifact_max_bytes,
    )
    agui = AguiRunService(
        sessions=session_service,
        runs=run_service,
        input_artifacts=input_service,
        bindings=binding_repository,
    )

    async def close() -> None:
        await redis.aclose()
        await engine.dispose()

    return ApiContainer(
        agents=AgentService(registry, clock=clock),
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
        close=close,
    )
