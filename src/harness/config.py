"""Application configuration."""

from typing import Literal

from pydantic import Field, SecretStr
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
    allow_unsafe_local_sandbox: bool = False
    cc_switch_settings_path: str = "~/.claude/settings.json"
    otel_enabled: bool = False
    local_auto_execute: bool = False
    api_bearer_token: SecretStr = SecretStr("")

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
    new_api_compatibility: Literal["full", "degraded", "unsupported"] = "full"
    new_api_capabilities: str = "streaming,tool_use"

    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = ""
    worker_poll_interval_seconds: float = 0.25
    worker_task_visibility_timeout_seconds: float = Field(default=60, gt=0)
    worker_task_retry_delay_seconds: float = Field(default=1, ge=0)
    worker_task_heartbeat_seconds: float = Field(default=20, gt=0)

    daytona_api_key: SecretStr = SecretStr("")
    daytona_api_url: str = "https://app.daytona.io/api"
    daytona_target: str = ""
    daytona_snapshot: str = ""
    daytona_remote_workspace_root: str = "/home/daytona/harness"
    daytona_claude_cli_version: str = "2.1.206"
    daytona_claude_cli_path: str = "/home/daytona/.local/bin/claude"
    daytona_delete_on_destroy: bool = True
    daytona_auto_stop_interval_minutes: int = Field(default=15, ge=1)
    daytona_auto_delete_interval_minutes: int = Field(default=60, ge=1)
    output_artifact_max_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    workspace_archive_max_bytes: int = Field(default=512 * 1024 * 1024, gt=0)
    workspace_archive_max_members: int = Field(default=10_000, gt=0)

    mcp_secret_references_json: str = "{}"
    mcp_server_secrets_json: SecretStr = SecretStr("{}")

    otlp_endpoint: str = ""
    otlp_headers: SecretStr = SecretStr("")
    otel_service_name: str = "claude-agent-harness"
    otel_environment: str = ""
