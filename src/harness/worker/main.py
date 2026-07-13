"""Worker entry helpers."""

import asyncio
import logging
import signal
from typing import Protocol

from harness.config import Settings
from harness.core.models import Run
from harness.core.ports import RunTask, TaskQueue
from harness.worker.orchestrator import RunOrchestrator

logger = logging.getLogger(__name__)


class RunExecutor(Protocol):
    async def execute(self, tenant_id: str, run_id: str) -> Run: ...


async def run_once(orchestrator: RunOrchestrator, tenant_id: str, run_id: str) -> Run:
    """Execute one already-dequeued Run."""

    return await orchestrator.execute(tenant_id, run_id)


async def _wait_for_work(stop: asyncio.Event, poll_interval: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=poll_interval)
    except TimeoutError:
        pass


async def worker_loop(
    queue: TaskQueue,
    executor: RunExecutor,
    *,
    stop: asyncio.Event,
    poll_interval: float,
) -> None:
    """Consume durable run tasks until shutdown is requested.

    A task is requeued only when execution escapes with an infrastructure error.
    Domain/runtime failures are terminal run results handled by the orchestrator.
    """

    while not stop.is_set():
        task: RunTask | None = await queue.dequeue()
        if task is None:
            await _wait_for_work(stop, poll_interval)
            continue
        try:
            await executor.execute(task.tenant_id, task.run_id)
        except Exception:
            logger.exception(
                "run task execution escaped unexpectedly",
                extra={"tenant_id": task.tenant_id, "run_id": task.run_id},
            )
            await queue.enqueue(task)
            await _wait_for_work(stop, poll_interval)


async def serve(settings: Settings) -> None:
    """Compose and run the production worker until SIGINT or SIGTERM."""

    from harness.composition import build_production_container

    container = build_production_container(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop.set)
        except NotImplementedError:  # pragma: no cover - Windows event loop
            pass
    try:
        await worker_loop(
            container.task_queue,
            container.worker,
            stop=stop,
            poll_interval=settings.worker_poll_interval_seconds,
        )
    finally:
        if container.close is not None:
            await container.close()


def entrypoint() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(Settings()))
