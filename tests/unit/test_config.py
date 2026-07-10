from harness.config import Settings


def test_local_defaults_disable_external_model_and_otel() -> None:
    settings = Settings()

    assert settings.environment == "local"
    assert settings.runtime == "fake"
    assert settings.otel_enabled is False
