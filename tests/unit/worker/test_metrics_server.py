import asyncio

import pytest

from harness.reliability.metrics import ReliabilityMetrics
from harness.worker.main import start_metrics_server


@pytest.mark.asyncio
async def test_worker_metrics_server_exposes_process_registry() -> None:
    metrics = ReliabilityMetrics()
    metrics.increment(
        "harness_trace_terminal_total", labels={"completeness": "complete"}
    )
    server = await start_metrics_server(metrics, host="127.0.0.1", port=0)
    socket = server.sockets[0]
    port = socket.getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /metrics HTTP/1.1\r\nHost: worker\r\n\r\n")
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()

    assert response.startswith(b"HTTP/1.1 200 OK")
    assert b'trace_terminal_total{completeness="complete"} 1' in response
