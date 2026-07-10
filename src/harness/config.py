"""Application configuration."""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings shared by the local API and worker processes."""

    model_config = SettingsConfigDict(
        env_prefix="HARNESS_",
        env_file=".env",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    runtime: Literal["fake", "claude-sdk"] = "fake"
    otel_enabled: bool = False
    local_auto_execute: bool = False

    database_url: str = "postgresql+asyncpg://harness:harness@localhost:5432/harness"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: SecretStr = SecretStr("")
    minio_secret_key: SecretStr = SecretStr("")
    minio_bucket: str = "harness-artifacts"
    minio_secure: bool = False

    new_api_base_url: str = ""
    new_api_key: SecretStr = SecretStr("")
    new_api_model: str = ""

    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_api_key: SecretStr = SecretStr("")

    otlp_endpoint: str = ""
    otlp_headers: SecretStr = SecretStr("")
    otel_service_name: str = "claude-agent-harness"
