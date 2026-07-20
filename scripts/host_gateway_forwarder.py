"""Forward a Docker-reachable host port to a macOS-only VPN route.

Colima does not inherit utun routes from macOS. This small TCP forwarder keeps
model traffic authenticated end-to-end while letting containers reach an
internal gateway through ``host.docker.internal``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal


async def _copy(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        while chunk := await reader.read(64 * 1024):
            writer.write(chunk)
            await writer.drain()
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


async def _serve(
    listen_host: str,
    listen_port: int,
    target_host: str,
    target_port: int,
) -> None:
    async def forward(
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                target_host,
                target_port,
            )
        except OSError:
            client_writer.close()
            await client_writer.wait_closed()
            return
        await asyncio.gather(
            _copy(client_reader, upstream_writer),
            _copy(upstream_reader, client_writer),
        )

    server = await asyncio.start_server(forward, listen_host, listen_port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(getattr(signal, name), stop.set)
    async with server:
        await stop.wait()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--target-port", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(
        _serve(
            args.listen_host,
            args.listen_port,
            args.target_host,
            args.target_port,
        )
    )


if __name__ == "__main__":
    main()
