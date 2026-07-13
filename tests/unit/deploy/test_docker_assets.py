from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).parents[3]
COMPOSE_PATH = ROOT / "deploy/docker-compose/compose.yaml"


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
    assert services["worker"]["environment"]["HARNESS_ENVIRONMENT"] == "production"
    assert services["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["web"]["depends_on"]["seed"]["condition"] == "service_completed_successfully"
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
    assert "output: \"standalone\"" in (
        ROOT / "web/harness-console/next.config.ts"
    ).read_text()


def test_runtime_entrypoints_and_environment_template_exist() -> None:
    api_entrypoint = ROOT / "deploy/docker/entrypoint-api.sh"
    worker_entrypoint = ROOT / "deploy/docker/entrypoint-worker.sh"
    environment = ROOT / "deploy/docker-compose/.env.docker.example"

    assert "uvicorn harness.api.app:app" in api_entrypoint.read_text()
    assert "harness-worker" in worker_entrypoint.read_text()
    values = environment.read_text()
    assert "HARNESS_NEW_API_BASE_URL=" in values
    assert "MINIO_ROOT_PASSWORD=" in values
    assert "LANGFUSE_OTLP_ENDPOINT=" in values
    assert "LANGFUSE_AUTHORIZATION=" in values


def test_dockerignore_excludes_secrets_and_build_outputs() -> None:
    ignored = (ROOT / ".dockerignore").read_text()

    for pattern in (".env", ".git", ".venv", "node_modules", ".next", ".DS_Store"):
        assert pattern in ignored
