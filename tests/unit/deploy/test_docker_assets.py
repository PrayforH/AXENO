from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).parents[3]
COMPOSE_PATH = ROOT / "deploy/docker-compose/compose.yaml"
COLLECTOR_PATH = ROOT / "deploy/otel-collector/collector.yaml"


def compose() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(COMPOSE_PATH.read_text()))


def test_compose_contains_deployable_application_and_infrastructure() -> None:
    services = cast(dict[str, Any], compose()["services"])

    assert {
        "postgres",
        "redis",
        "minio",
        "minio-init",
        "migrate",
        "api",
        "worker",
        "seed",
        "web",
        "otel-collector",
    } <= services.keys()
    assert services["api"]["environment"]["HARNESS_ENVIRONMENT"] == "production"
    assert services["api"]["environment"]["HARNESS_RUNTIME"] == "claude-sdk"
    assert "build" in services["api"]
    for name in ("migrate", "worker", "seed"):
        assert "build" not in services[name]
        assert services[name]["image"] == services["api"]["image"]
    assert services["worker"]["environment"]["HARNESS_ENVIRONMENT"] == "production"
    assert "HARNESS_NEW_API_KEY" in services["worker"]["environment"]
    assert "HARNESS_DAYTONA_API_KEY" in services["worker"]["environment"]
    assert "HARNESS_MCP_SERVER_SECRETS_JSON" in services["worker"]["environment"]
    assert services["worker"]["environment"]["HARNESS_PREFLIGHT_TIMEOUT_SECONDS"] == (
        "${HARNESS_PREFLIGHT_TIMEOUT_SECONDS:-180}"
    )
    # The control plane uses the compatible model route for semantic task titles.
    # Sandbox and business MCP credentials remain worker-only.
    assert "HARNESS_NEW_API_KEY" in services["api"]["environment"]
    assert "HARNESS_NEW_API_KEY" not in services["web"]["environment"]
    assert "HARNESS_DAYTONA_API_KEY" not in services["api"]["environment"]
    assert "HARNESS_MCP_SERVER_SECRETS_JSON" not in services["api"]["environment"]
    assert set(services["migrate"]["environment"]) == {"HARNESS_DATABASE_URL"}
    assert services["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["web"]["depends_on"]["seed"]["condition"] == "service_completed_successfully"
    assert (
        "public-opinion-agent/agent.yaml"
        in services["seed"]["environment"]["HARNESS_SEED_AGENT_MANIFESTS"]
    )
    assert services["otel-collector"]["profiles"] == ["observability"]
    assert "postgres-data" in compose()["volumes"]
    assert "redis-data" in compose()["volumes"]
    assert "minio-data" in compose()["volumes"]


def test_images_run_as_non_root_and_expose_health_checks() -> None:
    api = (ROOT / "deploy/docker/api.Dockerfile").read_text()
    web = (ROOT / "deploy/docker/web.Dockerfile").read_text()

    assert "USER harness" in api
    assert "USER nextjs" in web
    assert "HEALTHCHECK" in api
    assert "HEALTHCHECK" in web
    assert "--no-dev" in api
    assert "pypi.tuna.tsinghua.edu.cn" in api
    assert "registry.npmmirror.com" in web
    assert 'output: "standalone"' in (ROOT / "web/harness-console/next.config.ts").read_text()


def test_runtime_entrypoints_and_environment_template_exist() -> None:
    api_entrypoint = ROOT / "deploy/docker/entrypoint-api.sh"
    worker_entrypoint = ROOT / "deploy/docker/entrypoint-worker.sh"
    environment = ROOT / "deploy/docker-compose/.env.docker.example"

    assert "uvicorn harness.api.app:app" in api_entrypoint.read_text()
    assert "harness-worker" in worker_entrypoint.read_text()
    values = environment.read_text()
    assert "HARNESS_NEW_API_BASE_URL=" in values
    assert "HARNESS_API_BEARER_TOKEN=" in values
    assert "HARNESS_ALLOW_UNSAFE_LOCAL_SANDBOX=false" in values
    assert "HARNESS_SANDBOX_PROVIDER=daytona" in values
    assert "HARNESS_PREFLIGHT_TIMEOUT_SECONDS=180" in values
    assert "MINIO_ROOT_PASSWORD=" in values
    assert "LANGFUSE_OTLP_ENDPOINT=" in values
    assert "LANGFUSE_PUBLIC_KEY=" in values
    assert "LANGFUSE_SECRET_KEY=" in values
    assert "LANGFUSE_ENVIRONMENT=" in values
    assert "LANGFUSE_AUTHORIZATION=" not in values
    assert "HARNESS_AGENT_VERSION=0.4.0" in values
    assert compose()["services"]["web"]["environment"]["HARNESS_AGENT_VERSION"] == (
        "${HARNESS_AGENT_VERSION:-0.4.0}"
    )
    services = cast(dict[str, Any], compose()["services"])
    for name in ("api", "seed", "web"):
        assert "HARNESS_API_BEARER_TOKEN" in services[name]["environment"]
    assert "HARNESS_API_BEARER_TOKEN" not in services["worker"]["environment"]


def test_external_langfuse_collector_uses_basic_auth() -> None:
    collector = cast(dict[str, Any], yaml.safe_load(COLLECTOR_PATH.read_text()))

    assert collector["extensions"]["basicauth/client"]["client_auth"] == {
        "username": "${env:LANGFUSE_PUBLIC_KEY}",
        "password": "${env:LANGFUSE_SECRET_KEY}",
    }
    exporter = collector["exporters"]["otlphttp/langfuse"]
    assert exporter["auth"]["authenticator"] == "basicauth/client"
    assert exporter["headers"]["x-langfuse-ingestion-version"] == "4"
    assert "Authorization" not in exporter["headers"]
    assert collector["service"]["extensions"] == ["basicauth/client"]


def test_observability_profile_scopes_external_langfuse_secrets() -> None:
    services = cast(dict[str, Any], compose()["services"])
    collector = cast(dict[str, Any], services["otel-collector"])
    environment = cast(dict[str, Any], collector["environment"])

    assert collector["profiles"] == ["observability"]
    assert environment == {
        "LANGFUSE_OTLP_ENDPOINT": "${LANGFUSE_OTLP_ENDPOINT:-}",
        "LANGFUSE_PUBLIC_KEY": "${LANGFUSE_PUBLIC_KEY:-}",
        "LANGFUSE_SECRET_KEY": "${LANGFUSE_SECRET_KEY:-}",
    }
    assert collector["ports"] == [
        "127.0.0.1:${OTEL_GRPC_PORT:-4317}:4317",
        "127.0.0.1:${OTEL_HTTP_PORT:-4318}:4318",
    ]
    for name in ("api", "worker"):
        service_environment = cast(dict[str, Any], services[name]["environment"])
        assert service_environment["HARNESS_OTEL_ENVIRONMENT"] == (
            "${LANGFUSE_ENVIRONMENT:-production}"
        )
        assert "LANGFUSE_PUBLIC_KEY" not in service_environment
        assert "LANGFUSE_SECRET_KEY" not in service_environment
        assert "HARNESS_LANGFUSE_SECRET_KEY" not in service_environment
    quality_environment = cast(dict[str, Any], services["quality-sync"])["environment"]
    assert quality_environment["HARNESS_LANGFUSE_PUBLIC_KEY"] == (
        "${LANGFUSE_PUBLIC_KEY:?set LANGFUSE_PUBLIC_KEY}"
    )
    assert quality_environment["HARNESS_LANGFUSE_SECRET_KEY"] == (
        "${LANGFUSE_SECRET_KEY:?set LANGFUSE_SECRET_KEY}"
    )
    assert "HARNESS_NEW_API_KEY" not in quality_environment


def test_dockerignore_excludes_secrets_and_build_outputs() -> None:
    ignored = (ROOT / ".dockerignore").read_text()

    for pattern in (".env", ".git", ".venv", "node_modules", ".next", ".DS_Store"):
        assert pattern in ignored
