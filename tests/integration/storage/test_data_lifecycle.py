from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from harness.core.errors import NotFoundError
from harness.core.models import ExecutionIdentity, Session
from harness.lifecycle.models import (
    DataLifecycleJob,
    LifecycleAdapterResult,
    LifecycleAdapterStatus,
    LifecycleJobKind,
    LifecycleJobStatus,
    LifecycleScope,
    LifecycleScopeKind,
)
from harness.memory_bank.service import MemoryBankService
from harness.quality.models import QualityScore, ScoreSource
from harness.storage.lifecycle_adapters import (
    ExternalDeletionPendingError,
    LangfuseLifecycleAdapter,
    MemoryLifecycleAdapter,
    PostgresLifecycleAdapter,
)
from harness.storage.lifecycle_repository import PostgresDataLifecycleRepository
from harness.storage.memory_bank_repository import PostgresMemoryBankRepository
from harness.storage.models import (
    AuditLogRow,
    EnvironmentRow,
    QualityRuleRow,
    QualityScoreRow,
    SessionRow,
)
from tests.integration.storage.conftest import DatabaseFixture

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def job(
    tenant_id: str,
    job_id: str,
    *,
    kind: LifecycleJobKind = LifecycleJobKind.DELETE,
) -> DataLifecycleJob:
    return DataLifecycleJob(
        tenantId=tenant_id,
        jobId=job_id,
        kind=kind,
        scope=LifecycleScope(kind=LifecycleScopeKind.TENANT, subjectId=tenant_id),
        requestedBy="admin",
        idempotencyKey=f"key:{job_id}",
        status=LifecycleJobStatus.QUEUED,
        adapters=(
            LifecycleAdapterResult(
                adapter="postgresql",
                status=LifecycleAdapterStatus.PENDING,
                attempts=0,
                updatedAt=NOW,
            ),
        ),
        retentionCutoffs={
            "sessions": NOW - timedelta(days=30),
            "artifacts": NOW - timedelta(days=30),
            "traces": NOW - timedelta(days=14),
            "evals": NOW - timedelta(days=90),
        }
        if kind is LifecycleJobKind.RETENTION
        else {},
        createdAt=NOW,
        updatedAt=NOW,
    )


@pytest.mark.asyncio
async def test_lifecycle_repository_is_durable_fenced_and_tenant_scoped(
    database: DatabaseFixture,
) -> None:
    _, sessions = database
    repository = PostgresDataLifecycleRepository(sessions)
    stored = await repository.add_job(job("tenant-a", "job-a"))
    duplicate = await repository.add_job(job("tenant-a", "job-a"))
    assert duplicate.job_id == stored.job_id
    with pytest.raises(NotFoundError):
        await repository.get_job("tenant-b", "job-a")

    running = stored.model_copy(
        update={
            "status": LifecycleJobStatus.RUNNING,
            "fencing_token": 1,
            "updated_at": NOW,
        }
    )
    assert await repository.compare_and_set(LifecycleJobStatus.QUEUED, running)
    assert not await repository.compare_and_set(LifecycleJobStatus.QUEUED, running)


@pytest.mark.asyncio
async def test_retention_deletes_expired_sessions_but_preserves_audit_and_deployment_evidence(
    database: DatabaseFixture,
) -> None:
    _, sessions = database
    old_session = Session(
        session_id="session-old",
        tenant_id="tenant-a",
        user_id="user-a",
        agent_name="agent-a",
        agent_version="1.0.0",
        created_at=NOW - timedelta(days=120),
    )
    async with sessions() as db:
        db.add_all(
            [
                SessionRow(
                    tenant_id="tenant-a",
                    session_id=old_session.session_id,
                    user_id=old_session.user_id,
                    payload=old_session.model_dump(mode="json"),
                ),
                AuditLogRow(
                    audit_id="audit-a",
                    occurred_at=NOW,
                    tenant_id="tenant-a",
                    user_id="user-a",
                    action="session.create",
                    resource_type="session",
                    resource_id=old_session.session_id,
                    outcome="success",
                    ip_address=None,
                    user_agent=None,
                    details={},
                ),
                EnvironmentRow(
                    tenant_id="tenant-a",
                    agent_name="agent-a",
                    name="production",
                    revision=1,
                    updated_at=NOW,
                    payload={"pointer": "1.0.0"},
                ),
                QualityRuleRow(
                    tenant_id="tenant-a",
                    rule_id="rule-a",
                    agent_name="agent-a",
                    payload={"name": "keep operational rule"},
                ),
            ]
        )
        await db.commit()

    count = await PostgresLifecycleAdapter(sessions).delete(
        job("tenant-a", "retention-a", kind=LifecycleJobKind.RETENTION)
    )
    assert count == 1
    async with sessions() as db:
        assert await db.get(SessionRow, ("tenant-a", "session-old")) is None
        assert await db.get(AuditLogRow, "audit-a") is not None
        environment = await db.scalar(
            select(EnvironmentRow).where(EnvironmentRow.tenant_id == "tenant-a")
        )
        assert environment is not None
        assert await db.get(QualityRuleRow, ("tenant-a", "rule-a")) is not None


@pytest.mark.asyncio
async def test_memory_lifecycle_exports_and_deletes_only_requested_user_scope(
    database: DatabaseFixture,
) -> None:
    _, sessions = database
    memory = MemoryBankService(
        PostgresMemoryBankRepository(sessions), clock=lambda: NOW
    )

    def memory_identity(user_id: str) -> ExecutionIdentity:
        return ExecutionIdentity(
            tenant_id="tenant-a",
            user_id=user_id,
            project_id="agent-a",
            session_id=f"session-{user_id}",
            run_id=f"run-{user_id}",
            agent_name="agent-a",
            agent_version="1.0.0",
        )

    first = await memory.propose_agent(memory_identity("user-a"), "偏好中文简报")
    await memory.confirm("tenant-a", "user-a", first.entry_id, first.version)
    second = await memory.propose_agent(memory_identity("user-b"), "偏好英文简报")
    await memory.confirm("tenant-a", "user-b", second.entry_id, second.version)
    await memory.replace_consent(
        "tenant-a",
        "user-a",
        "agent-a",
        expected_version=0,
        allow_agent_personal=True,
    )
    scoped = job("tenant-a", "memory-user-a").model_copy(
        update={
            "scope": LifecycleScope(
                kind=LifecycleScopeKind.USER, subjectId="user-a"
            )
        }
    )
    adapter = MemoryLifecycleAdapter(sessions)

    exported, count = await adapter.export(scoped)

    assert count == 2
    assert isinstance(exported, dict)
    bank = cast(dict[str, list[dict[str, object]]], exported["memoryBank"])
    assert [entry["userId"] for entry in bank["entries"]] == ["user-a"]
    assert await adapter.delete(scoped) == 2
    assert await memory.list_entries("tenant-a", "user-a") == ()
    assert len(await memory.list_entries("tenant-a", "user-b")) == 1


@pytest.mark.asyncio
async def test_langfuse_delete_stays_retryable_until_trace_is_absent(
    database: DatabaseFixture,
) -> None:
    _, sessions = database
    trace_id = "a" * 32
    score = QualityScore(
        tenantId="tenant-a",
        scoreId="score-a",
        runId="run-a",
        traceId=trace_id,
        sessionId="session-a",
        agentName="agent-a",
        agentVersion="1.0.0",
        name="rule.success",
        value=1,
        source=ScoreSource.RULE,
        createdBy="system",
        createdAt=NOW,
    )
    async with sessions() as db:
        db.add(
            QualityScoreRow(
                tenant_id="tenant-a",
                score_id=score.score_id,
                run_id=score.run_id,
                agent_name=score.agent_name,
                agent_version=score.agent_version,
                name=score.name,
                created_at=score.created_at,
                payload=score.model_dump(mode="json", by_alias=True),
            )
        )
        await db.commit()

    verification_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal verification_count
        assert request.headers["authorization"].startswith("Basic ")
        if request.method == "DELETE":
            return httpx.Response(202)
        verification_count += 1
        return httpx.Response(200 if verification_count == 1 else 404, json={})

    adapter = LangfuseLifecycleAdapter(
        sessions,
        base_url="https://langfuse.test",
        public_key="pk-test",
        secret_key=SecretStr("sk-test"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ExternalDeletionPendingError):
        await adapter.delete(job("tenant-a", "delete-a"))
    assert await adapter.delete(job("tenant-a", "delete-a")) == 1
