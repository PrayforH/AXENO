import pytest

from harness.config import Settings


def test_local_defaults_disable_external_model_and_otel() -> None:
    settings = Settings()

    assert settings.environment == "local"
    assert settings.runtime == "fake"
    assert settings.otel_enabled is False
    assert settings.cc_switch_settings_path == "~/.claude/settings.json"
    assert settings.new_api_compatibility == "full"
    assert settings.new_api_capabilities == "streaming,tool_use"
    assert settings.daytona_delete_on_destroy is True
    assert settings.daytona_auto_stop_interval_minutes == 15
    assert settings.daytona_auto_delete_interval_minutes == 60
    assert settings.preflight_timeout_seconds == 180


def test_daytona_cleanup_intervals_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Settings(daytona_auto_stop_interval_minutes=0)
    with pytest.raises(ValueError):
        Settings(daytona_auto_delete_interval_minutes=0)
