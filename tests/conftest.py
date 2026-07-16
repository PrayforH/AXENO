"""Keep committed tests deterministic when a developer has a real local .env."""

import pytest


@pytest.fixture(autouse=True)
def deterministic_harness_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_RUNTIME", "fake")
    monkeypatch.setenv("HARNESS_OTEL_ENABLED", "false")
    monkeypatch.setenv("HARNESS_OTEL_SERVICE_NAME", "claude-agent-harness")
