import pytest

from scripts.e2e_fake_runtime import run_fake_e2e


@pytest.mark.asyncio
async def test_local_fake_runtime_stack() -> None:
    report = await run_fake_e2e()

    assert report["status"] == "succeeded"
    assert report["otel_enabled"] is False
    assert report["agui_events"] >= 10
