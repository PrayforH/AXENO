import json
from pathlib import Path

import pytest

from harness.api.dependencies import build_memory_container
from harness.config import Settings
from harness.runtime.cc_switch import CcSwitchConfigError
from harness.runtime.fake import FakeRuntime
from harness.runtime.registry_runtime import RegistryClaudeRuntime


def test_default_composition_uses_fake_runtime() -> None:
    container = build_memory_container(settings=Settings(runtime="fake"))

    assert isinstance(container.runtime, FakeRuntime)


def test_claude_sdk_composition_loads_cc_switch_runtime(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://gateway.example",
                    "ANTHROPIC_AUTH_TOKEN": "composition-secret",
                    "ANTHROPIC_MODEL": "composition-model",
                }
            }
        ),
        encoding="utf-8",
    )

    container = build_memory_container(
        settings=Settings(
            runtime="claude-sdk",
            cc_switch_settings_path=str(path),
        )
    )

    assert isinstance(container.runtime, RegistryClaudeRuntime)
    assert "composition-secret" not in repr(container)


def test_claude_sdk_composition_fails_instead_of_falling_back(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    with pytest.raises(CcSwitchConfigError, match="not found"):
        build_memory_container(
            settings=Settings(
                runtime="claude-sdk",
                cc_switch_settings_path=str(missing_path),
            )
        )
