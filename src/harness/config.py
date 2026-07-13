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
    sandbox_provider: Literal["local", "daytona"] = "local"
    cc_switch_settings_path: str = "~/.claude/settings.json"
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
    anthropic_model: str = ""
    worker_poll_interval_seconds: float = 0.25

    daytona_api_key: SecretStr = SecretStr("")
    daytona_api_url: str = "https://app.daytona.io/api"
    daytona_target: str = ""
    daytona_snapshot: str = ""
    daytona_remote_workspace_root: str = "/workspace/harness"
    daytona_claude_cli_version: str = "2.1.206"
    daytona_delete_on_destroy: bool = False
    output_artifact_max_bytes: int = 50 * 1024 * 1024

    mcp_secret_references_json: str = "{}"
    mcp_server_secrets_json: SecretStr = SecretStr("{}")

    otlp_endpoint: str = ""
    otlp_headers: SecretStr = SecretStr("")
    otel_service_name: str = "claude-agent-harness"
