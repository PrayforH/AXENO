from datetime import UTC, datetime

import pytest

from harness.core.models import ExecutionIdentity
from harness.memory_bank.eval import MemoryRecallEvalCase, MemoryRecallEvalRunner
from harness.memory_bank.repositories import InMemoryMemoryBankRepository
from harness.memory_bank.service import MemoryBankService


def identity() -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="agent-a",
        session_id="session-a",
        run_id="run-a",
        agent_name="agent-a",
        agent_version="1.0.0",
    )


@pytest.mark.asyncio
async def test_recall_eval_scores_correct_missing_and_false_recall_cases() -> None:
    service = MemoryBankService(
        InMemoryMemoryBankRepository(),
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
    )
    preferred = await service.propose_agent(identity(), "报告默认使用中文简报")
    preferred = await service.confirm(
        "tenant-a", "user-a", preferred.entry_id, preferred.version
    )
    removed = await service.propose_agent(identity(), "报告默认使用红色主题")
    removed = await service.confirm(
        "tenant-a", "user-a", removed.entry_id, removed.version
    )
    await service.delete("tenant-a", "user-a", removed.entry_id, removed.version)

    results = await MemoryRecallEvalRunner(service).run(
        (
            MemoryRecallEvalCase(
                "correct-recall",
                "tenant-a",
                "user-a",
                "agent-a",
                "中文简报",
                frozenset({preferred.entry_id}),
                frozenset({removed.entry_id}),
            ),
            MemoryRecallEvalCase(
                "no-false-recall",
                "tenant-a",
                "user-a",
                "agent-a",
                "财务预算",
                frozenset(),
                frozenset({preferred.entry_id, removed.entry_id}),
            ),
        )
    )

    assert all(result.passed for result in results)
    assert results[0].precision == results[0].recall == 1
    assert results[1].recalled_entry_ids == ()
