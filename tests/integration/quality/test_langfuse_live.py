import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

from harness.quality.langfuse import LangfuseQualityExporter
from harness.quality.models import QualityScore, ScoreSource


@pytest.mark.asyncio
async def test_langfuse_score_export_live_opt_in() -> None:
    if os.getenv("HARNESS_LANGFUSE_LIVE") != "1":
        pytest.skip("set HARNESS_LANGFUSE_LIVE=1 for real Langfuse score smoke")
    base_url = os.environ["HARNESS_LANGFUSE_BASE_URL"]
    public_key = os.environ["HARNESS_LANGFUSE_PUBLIC_KEY"]
    secret_key = SecretStr(os.environ["HARNESS_LANGFUSE_SECRET_KEY"])
    unique = uuid4().hex
    exporter = LangfuseQualityExporter(
        base_url=base_url,
        public_key=public_key,
        secret_key=secret_key,
    )
    await exporter.export_score(
        QualityScore(
            tenantId="live-smoke",
            scoreId=f"harness-live-{unique}",
            runId=f"run-{unique}",
            traceId=unique,
            sessionId=f"session-{unique}",
            agentName="harness-live-smoke",
            agentVersion="0.0.0-smoke",
            name="integration_reachable",
            value=1,
            source=ScoreSource.RULE,
            createdBy="live-smoke",
            createdAt=datetime.now(UTC),
        )
    )
