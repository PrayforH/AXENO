import asyncio

import pytest

from harness.core.models import Run
from harness.core.ports import RunTask
from harness.worker.main import maintenance_loop, worker_loop


class Queue:
    def __init__(self, tasks: list[RunTask], *, fail_lease_renewal: bool = False) -> None:
        self.tasks = tasks
        self.fail_lease_renewal = fail_lease_renewal
        self.acknowledged: list[RunTask] = []
        self.retried: list[RunTask] = []
        self.extended: list[RunTask] = []

    async def enqueue(self, task: RunTask) -> None:
        self.tasks.append(task)

    async def dequeue(self) -> RunTask | None:
        return self.tasks.pop(0) if self.tasks else None

    async def acknowledge(self, task: RunTask) -> None:
        self.acknowledged.append(task)

    async def retry(self, task: RunTask) -> None:
        self.retried.append(task)
        self.tasks.append(task)

    async def extend_lease(self, task: RunTask) -> None:
        if self.fail_lease_renewal:
            raise RuntimeError("redis unavailable")
        self.extended.append(task)


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


class SlowExecutor:
    def __init__(self, stop: asyncio.Event) -> None:
        self.stop = stop
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, tenant_id: str, run_id: str) -> Run:
        del tenant_id, run_id
        self.started.set()
        await self.release.wait()
        self.stop.set()
        return Run.model_construct()


class ParallelExecutor:
    def __init__(self, stop: asyncio.Event, total: int) -> None:
        self.stop = stop
        self.total = total
        self.active = 0
        self.maximum_active = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = 0

    async def execute(self, tenant_id: str, run_id: str) -> Run:
        del tenant_id, run_id
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        if self.active == self.total:
            self.started.set()
        await self.release.wait()
        self.active -= 1
        self.completed += 1
        if self.completed == self.total:
            self.stop.set()
        return Run.model_construct()


class SessionSerialExecutor:
    def __init__(self, stop: asyncio.Event) -> None:
        self.stop = stop
        self.first_started = asyncio.Event()
        self.second_started = asyncio.Event()
        self.release_first = asyncio.Event()
        self.order: list[str] = []

    async def execute(self, tenant_id: str, run_id: str) -> Run:
        del tenant_id
        self.order.append(f"start:{run_id}")
        if run_id == "run-1":
            self.first_started.set()
            await self.release_first.wait()
        else:
            self.second_started.set()
        self.order.append(f"end:{run_id}")
        if run_id == "run-2":
            self.stop.set()
        return Run.model_construct()


@pytest.mark.asyncio
async def test_worker_loop_executes_scoped_task_and_stops() -> None:
    stop = asyncio.Event()
    queue = Queue([RunTask(tenant_id="tenant-a", run_id="run-1")])
    executor = Executor(stop)

    await worker_loop(queue, executor, stop=stop, poll_interval=0.001)

    assert executor.calls == [("tenant-a", "run-1")]
    assert queue.acknowledged == [RunTask(tenant_id="tenant-a", run_id="run-1")]
    assert queue.retried == []


@pytest.mark.asyncio
async def test_worker_loop_requeues_task_after_unexpected_failure() -> None:
    stop = asyncio.Event()
    task = RunTask(tenant_id="tenant-a", run_id="run-1")
    queue = Queue([task])
    executor = Executor(stop, fail=True)

    await worker_loop(queue, executor, stop=stop, poll_interval=0.001)

    assert queue.retried == [task]
    assert queue.acknowledged == []


@pytest.mark.asyncio
async def test_worker_loop_can_stop_while_queue_is_empty() -> None:
    stop = asyncio.Event()
    queue = Queue([])
    executor = Executor(stop)
    task = asyncio.create_task(worker_loop(queue, executor, stop=stop, poll_interval=60))

    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=0.1)

    assert executor.calls == []


@pytest.mark.asyncio
async def test_worker_loop_runs_different_sessions_concurrently() -> None:
    stop = asyncio.Event()
    tasks = [
        RunTask(tenant_id="tenant-a", run_id="run-1", session_id="session-1"),
        RunTask(tenant_id="tenant-a", run_id="run-2", session_id="session-2"),
    ]
    queue = Queue(tasks.copy())
    executor = ParallelExecutor(stop, total=2)
    worker = asyncio.create_task(
        worker_loop(
            queue,
            executor,
            stop=stop,
            poll_interval=0.001,
            concurrency=2,
        )
    )

    await asyncio.wait_for(executor.started.wait(), timeout=0.1)
    assert executor.maximum_active == 2
    executor.release.set()
    await asyncio.wait_for(worker, timeout=0.2)

    assert queue.acknowledged == tasks


@pytest.mark.asyncio
async def test_worker_loop_serializes_runs_from_the_same_session() -> None:
    stop = asyncio.Event()
    tasks = [
        RunTask(tenant_id="tenant-a", run_id="run-1", session_id="session-1"),
        RunTask(tenant_id="tenant-a", run_id="run-2", session_id="session-1"),
    ]
    queue = Queue(tasks.copy())
    executor = SessionSerialExecutor(stop)
    worker = asyncio.create_task(
        worker_loop(
            queue,
            executor,
            stop=stop,
            poll_interval=0.001,
            concurrency=2,
        )
    )

    await asyncio.wait_for(executor.first_started.wait(), timeout=0.1)
    await asyncio.sleep(0)
    assert not executor.second_started.is_set()
    executor.release_first.set()
    await asyncio.wait_for(executor.second_started.wait(), timeout=0.1)
    await asyncio.wait_for(worker, timeout=0.2)

    assert executor.order == ["start:run-1", "end:run-1", "start:run-2", "end:run-2"]
    assert queue.acknowledged == tasks


@pytest.mark.asyncio
async def test_worker_runs_expiry_maintenance_while_queue_is_idle() -> None:
    stop = asyncio.Event()
    queue = Queue([])
    executor = Executor(stop)
    calls = 0

    async def maintenance() -> object:
        nonlocal calls
        calls += 1
        stop.set()
        return 0

    await worker_loop(
        queue,
        executor,
        stop=stop,
        poll_interval=60,
        maintenance=maintenance,
    )

    assert calls == 1
    assert executor.calls == []


@pytest.mark.asyncio
async def test_worker_loop_renews_lease_during_long_execution() -> None:
    stop = asyncio.Event()
    task = RunTask(tenant_id="tenant-a", run_id="run-1")
    queue = Queue([task])
    executor = SlowExecutor(stop)
    worker = asyncio.create_task(
        worker_loop(
            queue,
            executor,
            stop=stop,
            poll_interval=0.001,
            lease_heartbeat_interval=0.01,
        )
    )

    await executor.started.wait()
    await asyncio.sleep(0.025)
    executor.release.set()
    await asyncio.wait_for(worker, timeout=0.2)

    assert queue.extended
    assert queue.acknowledged == [task]


@pytest.mark.asyncio
async def test_worker_continues_when_lease_renewal_temporarily_fails() -> None:
    stop = asyncio.Event()
    task = RunTask(tenant_id="tenant-a", run_id="run-1")
    queue = Queue([task], fail_lease_renewal=True)
    executor = SlowExecutor(stop)
    worker = asyncio.create_task(
        worker_loop(
            queue,
            executor,
            stop=stop,
            poll_interval=0.001,
            lease_heartbeat_interval=0.005,
        )
    )

    await executor.started.wait()
    await asyncio.sleep(0.012)
    executor.release.set()
    await asyncio.wait_for(worker, timeout=0.2)

    assert queue.acknowledged == [task]


@pytest.mark.asyncio
async def test_control_plane_maintenance_runs_while_a_child_run_is_active() -> None:
    stop = asyncio.Event()
    queue = Queue([RunTask(tenant_id="tenant-a", run_id="run-1")])
    executor = SlowExecutor(stop)
    reconciled = asyncio.Event()

    async def reconcile() -> object:
        reconciled.set()
        return 0

    worker = asyncio.create_task(worker_loop(queue, executor, stop=stop, poll_interval=0.001))
    controller = asyncio.create_task(
        maintenance_loop(
            reconcile,
            stop=stop,
            poll_interval=0.001,
            label="eval",
        )
    )

    await executor.started.wait()
    await asyncio.wait_for(reconciled.wait(), timeout=0.1)
    assert not worker.done()
    executor.release.set()
    await asyncio.gather(worker, controller)
