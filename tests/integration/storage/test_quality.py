from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from harness.quality.models import (
    AlertIncident,
    AlertRule,
    AlertState,
    QualityScore,
    QualitySyncJob,
    QualitySyncStatus,
    ScoreSource,
)
from harness.storage.database import SessionFactory
from harness.storage.quality_repository import PostgresQualityRepository

DatabaseFixture = tuple[AsyncEngine, SessionFactory]


@pytest.mark.asyncio
async def test_postgres_quality_facts_survive_repository_restart(
    database: DatabaseFixture,
) -> None:
    _engine, sessions = database
    repository = PostgresQualityRepository(sessions)
    now = datetime.now(UTC)
    score = QualityScore(
        tenantId="tenant-a",
        scoreId="score-a",
        runId="run-a",
        traceId="a" * 32,
        sessionId="session-a",
        agentName="agent-a",
        agentVersion="1.0.0",
        name="terminal_success",
        value=1,
        source=ScoreSource.RULE,
        createdBy="system",
        createdAt=now,
    )
    rule = AlertRule(
        tenantId="tenant-a",
        ruleId="rule-a",
        agentName="agent-a",
        scoreName="terminal_success",
        minimumValue=0.9,
        createdBy="release-manager",
        createdAt=now,
    )
    incident = AlertIncident(
        tenantId="tenant-a",
        incidentId="incident-a",
        ruleId="rule-a",
        agentName="agent-a",
        agentVersion="1.0.0",
        ownerUserId="release-manager",
        state=AlertState.OPEN,
        observedValue=0,
        sampleCount=1,
        openedAt=now,
    )
    sync = QualitySyncJob(
        tenantId="tenant-a",
        syncId="sync-a",
        kind="score",
        resourceId="score-a",
        status=QualitySyncStatus.QUEUED,
        createdAt=now,
        updatedAt=now,
    )
    await repository.add_score(score)
    await repository.add_rule(rule)
    await repository.upsert_incident(incident)
    await repository.add_sync(sync)

    restarted = PostgresQualityRepository(sessions)
    assert await restarted.get_score("tenant-a", "score-a") == score
    assert await restarted.list_rules("tenant-a", "agent-a") == [rule]
    assert await restarted.list_incidents("tenant-a", "agent-a") == [incident]
    assert await restarted.get_sync("tenant-a", "sync-a") == sync
