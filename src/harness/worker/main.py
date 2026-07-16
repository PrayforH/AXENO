"""Worker entry helpers."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
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


async def _renew_task_lease(
    queue: TaskQueue,
    task: RunTask,
    *,
    stop: asyncio.Event,
    interval: float,
) -> None:
    while not stop.is_set():
        await _wait_for_work(stop, interval)
        if not stop.is_set():
            try:
                await queue.extend_lease(task)
            except Exception:
                # A transient Redis failure must not terminate the worker while
                # the executor is still producing a terminal Run state. The
                # visibility lease may expire and cause a duplicate delivery,
                # which is safe because Run fencing rejects the stale owner.
                logger.exception(
                    "run task lease renewal failed",
                    extra={"tenant_id": task.tenant_id, "run_id": task.run_id},
                )


async def worker_loop(
    queue: TaskQueue,
    executor: RunExecutor,
    *,
    stop: asyncio.Event,
    poll_interval: float,
    lease_heartbeat_interval: float = 20,
    maintenance: Callable[[], Awaitable[object]] | None = None,
) -> None:
    """Consume durable run tasks until shutdown is requested.

    A task is requeued only when execution escapes with an infrastructure error.
    Domain/runtime failures are terminal run results handled by the orchestrator.
    """

    while not stop.is_set():
        if maintenance is not None:
            try:
                await maintenance()
            except Exception:
                logger.exception("worker maintenance failed")
        task: RunTask | None = await queue.dequeue()
        if task is None:
            await _wait_for_work(stop, poll_interval)
            continue
        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            _renew_task_lease(
                queue,
                task,
                stop=heartbeat_stop,
                interval=lease_heartbeat_interval,
            )
        )
        try:
            await executor.execute(task.tenant_id, task.run_id)
        except Exception:
            logger.exception(
                "run task execution escaped unexpectedly",
                extra={"tenant_id": task.tenant_id, "run_id": task.run_id},
            )
            await queue.retry(task)
            await _wait_for_work(stop, poll_interval)
        else:
            await queue.acknowledge(task)
        finally:
            heartbeat_stop.set()
            await heartbeat


async def maintenance_loop(
    maintenance: Callable[[], Awaitable[object]],
    *,
    stop: asyncio.Event,
    poll_interval: float,
    label: str,
) -> None:
    """Run an independent control-plane reconciler beside Run execution."""

    while not stop.is_set():
        try:
            await maintenance()
        except Exception:
            logger.exception("%s maintenance failed", label)
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

        async def preview_maintenance() -> None:
            await container.approvals.reap_expired()
            await container.quotas.reap_expired_all()
            await container.preview_controller.process_once()
            await container.preview_controller.reap_expired()

        async def eval_maintenance() -> None:
            await container.eval_controller.process_once()

        async def deployment_maintenance() -> None:
            await container.deployment_controller.process_once()

        control_tasks = [
            asyncio.create_task(
                maintenance_loop(
                    preview_maintenance,
                    stop=stop,
                    poll_interval=settings.worker_poll_interval_seconds,
                    label="preview",
                )
            ),
            asyncio.create_task(
                maintenance_loop(
                    eval_maintenance,
                    stop=stop,
                    poll_interval=settings.worker_poll_interval_seconds,
                    label="eval",
                )
            ),
            asyncio.create_task(
                maintenance_loop(
                    deployment_maintenance,
                    stop=stop,
                    poll_interval=settings.worker_poll_interval_seconds,
                    label="deployment",
                )
            ),
        ]
        if container.sandbox_maintenance is not None:
            control_tasks.append(
                asyncio.create_task(
                    maintenance_loop(
                        container.sandbox_maintenance,
                        stop=stop,
                        poll_interval=settings.kubernetes_reaper_interval_seconds,
                        label="sandbox-reaper",
                    )
                )
            )
        try:
            await worker_loop(
                container.task_queue,
                container.worker,
                stop=stop,
                poll_interval=settings.worker_poll_interval_seconds,
                lease_heartbeat_interval=settings.worker_task_heartbeat_seconds,
            )
        finally:
            stop.set()
            await asyncio.gather(*control_tasks)
    finally:
        if container.close is not None:
            await container.close()


def entrypoint() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(Settings()))
