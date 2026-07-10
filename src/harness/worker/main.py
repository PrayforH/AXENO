"""Worker entry helpers."""

from harness.core.models import Run
from harness.worker.orchestrator import RunOrchestrator


async def run_once(orchestrator: RunOrchestrator, tenant_id: str, run_id: str) -> Run:
    """Execute one already-dequeued Run."""

    return await orchestrator.execute(tenant_id, run_id)

