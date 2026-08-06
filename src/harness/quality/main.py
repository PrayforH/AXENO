"""Dedicated fail-open Langfuse quality projection worker."""

import asyncio
import signal

from harness.config import Settings


async def serve(settings: Settings) -> None:
    from harness.composition import build_production_container

    container = build_production_container(settings, execution_enabled=False)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop.set)
        except NotImplementedError:  # pragma: no cover
            pass
    try:
        while not stop.is_set():
            await container.quality_controller.process_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_interval_seconds)
            except TimeoutError:
                pass
    finally:
        if container.close is not None:
            await container.close()


def entrypoint() -> None:
    asyncio.run(serve(Settings()))


if __name__ == "__main__":  # pragma: no cover
    entrypoint()
