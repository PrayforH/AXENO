import json
from pathlib import Path

import pytest

from harness.runtime.cc_switch import CcSwitchConfigError, load_cc_switch_claude_config


def write_settings(path: Path, env: dict[str, str]) -> None:
    path.write_text(json.dumps({"env": env}), encoding="utf-8")


def test_loads_anthropic_compatible_provider_without_exposing_token(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    write_settings(
        path,
        {
            "ANTHROPIC_BASE_URL": "https://gateway.example",
            "ANTHROPIC_AUTH_TOKEN": "sensitive-token",
            "ANTHROPIC_MODEL": "gateway-model",
        },
    )

    config = load_cc_switch_claude_config(path)

    assert config.base_url == "https://gateway.example"
    assert config.model == "gateway-model"
    assert config.provider == "new-api"
    assert config.compatibility.value == "full"
    assert config.capabilities == frozenset({"streaming", "tool_use"})
    assert config.credential.get_secret_value() == "sensitive-token"
    assert "sensitive-token" not in repr(config)


def test_uses_api_key_and_sonnet_alias_for_official_provider(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    write_settings(
        path,
        {
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_API_KEY": "official-secret",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet",
        },
    )

    config = load_cc_switch_claude_config(path)

    assert config.provider == "anthropic"
    assert config.model == "claude-sonnet"
    assert "official-secret" not in repr(config)


@pytest.mark.parametrize(
    ("env", "missing_name"),
    [
        ({"ANTHROPIC_AUTH_TOKEN": "never-print", "ANTHROPIC_MODEL": "m"}, "base URL"),
        (
            {"ANTHROPIC_BASE_URL": "https://gateway", "ANTHROPIC_AUTH_TOKEN": "never-print"},
            "model",
        ),
        ({"ANTHROPIC_BASE_URL": "https://gateway", "ANTHROPIC_MODEL": "m"}, "credential"),
    ],
)
def test_rejects_missing_required_fields_without_exposing_values(
    tmp_path: Path,
    env: dict[str, str],
    missing_name: str,
) -> None:
    path = tmp_path / "settings.json"
    write_settings(path, env)

    with pytest.raises(CcSwitchConfigError, match=missing_name) as captured:
        load_cc_switch_claude_config(path)

    assert "never-print" not in str(captured.value)


def test_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(CcSwitchConfigError, match="valid JSON"):
        load_cc_switch_claude_config(path)


def test_expands_home_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    write_settings(
        tmp_path / "settings.json",
        {
            "ANTHROPIC_BASE_URL": "https://gateway",
            "ANTHROPIC_AUTH_TOKEN": "secret",
            "ANTHROPIC_MODEL": "model",
        },
    )

    config = load_cc_switch_claude_config("~/settings.json")

    assert config.model == "model"
