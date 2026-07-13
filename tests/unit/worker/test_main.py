import asyncio

import pytest

from harness.core.models import Run
from harness.core.ports import RunTask
from harness.worker.main import worker_loop


class Queue:
    def __init__(self, tasks: list[RunTask]) -> None:
        self.tasks = tasks
        self.enqueued: list[RunTask] = []

    async def enqueue(self, task: RunTask) -> None:
        self.enqueued.append(task)
        self.tasks.append(task)

    async def dequeue(self) -> RunTask | None:
        return self.tasks.pop(0) if self.tasks else None


class Executor:
    def __init__(self, stop: asyncio.Event, *, fail: bool = False) -> None:
        self.stop = stop
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def execute(self, tenant_id: str, run_id: str) -> Run:
        self.calls.append((tenant_id, run_id))
        self.stop.set()
        if self.fail:
            raise RuntimeError("database unavailable")
        return Run.model_construct()


@pytest.mark.asyncio
async def test_worker_loop_executes_scoped_task_and_stops() -> None:
    stop = asyncio.Event()
    queue = Queue([RunTask(tenant_id="tenant-a", run_id="run-1")])
    executor = Executor(stop)

    await worker_loop(queue, executor, stop=stop, poll_interval=0.001)

    assert executor.calls == [("tenant-a", "run-1")]
    assert queue.enqueued == []


@pytest.mark.asyncio
async def test_worker_loop_requeues_task_after_unexpected_failure() -> None:
    stop = asyncio.Event()
    task = RunTask(tenant_id="tenant-a", run_id="run-1")
    queue = Queue([task])
    executor = Executor(stop, fail=True)

    await worker_loop(queue, executor, stop=stop, poll_interval=0.001)

    assert queue.enqueued == [task]


@pytest.mark.asyncio
async def test_worker_loop_can_stop_while_queue_is_empty() -> None:
    stop = asyncio.Event()
    queue = Queue([])
    executor = Executor(stop)
    task = asyncio.create_task(
        worker_loop(queue, executor, stop=stop, poll_interval=60)
    )

    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=0.1)

    assert executor.calls == []
