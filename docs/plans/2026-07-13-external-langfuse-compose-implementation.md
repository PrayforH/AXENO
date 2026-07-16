# External Langfuse Compose Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make external Langfuse Cloud or self-hosted OTLP ingestion a safe, optional Docker Compose profile configured with endpoint, public key, secret key, and environment.

**Architecture:** Harness API and Worker export OTLP/HTTP only to the internal Collector. The Collector authenticates to external Langfuse with its Basic Auth client extension, adds the real-time ingestion header, and is started only through the existing `observability` profile. The application remains vendor-neutral by exposing the deployment environment as an OpenTelemetry resource attribute.

**Tech Stack:** Docker Compose, OpenTelemetry Collector Contrib, OTLP/HTTP, Langfuse OTLP ingestion, pytest, PyYAML, Pydantic Settings.

---

### Task 1: Lock the Collector and Compose contract with failing tests

**Files:**

- Modify: `tests/unit/deploy/test_docker_assets.py`
- Test: `tests/unit/deploy/test_docker_assets.py`

**Step 1: Write the failing tests**

Add assertions that:

- `deploy/otel-collector/collector.yaml` defines `basicauth/client` with public and secret key environment variables.
- `otlphttp/langfuse` uses `auth.authenticator: basicauth/client` and retains `x-langfuse-ingestion-version: "4"`.
- the Collector service registers the extension.
- Compose passes `LANGFUSE_OTLP_ENDPOINT`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` only to the profiled Collector.
- API/Worker receive `HARNESS_OTEL_ENVIRONMENT` and the Collector host ports bind to `127.0.0.1`.
- `.env.docker.example` exposes the four user-facing Langfuse values and no longer exposes `LANGFUSE_AUTHORIZATION`.

**Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/unit/deploy/test_docker_assets.py -q
```

Expected: FAIL because the current Collector uses a pre-encoded Authorization header.

**Step 3: Commit only after Task 2 implementation is green**

The test and implementation will be committed together after Task 2.

### Task 2: Implement optional external Langfuse authentication

**Files:**

- Modify: `deploy/otel-collector/collector.yaml`
- Modify: `deploy/docker-compose/compose.yaml`
- Modify: `deploy/docker-compose/.env.docker.example`
- Test: `tests/unit/deploy/test_docker_assets.py`

**Step 1: Add Collector Basic Auth**

Define:

```yaml
extensions:
  basicauth/client:
    client_auth:
      username: ${env:LANGFUSE_PUBLIC_KEY}
      password: ${env:LANGFUSE_SECRET_KEY}
```

Reference it from `otlphttp/langfuse.auth.authenticator`, keep the ingestion-version header, and register `basicauth/client` in `service.extensions`.

**Step 2: Update Compose**

- Replace `LANGFUSE_AUTHORIZATION` with required public and secret key variables on `otel-collector`.
- Keep `LANGFUSE_OTLP_ENDPOINT` required only when the `observability` profile is enabled.
- Bind optional Collector host ports to `127.0.0.1`.
- Set `HARNESS_OTEL_ENVIRONMENT` for API and Worker from `LANGFUSE_ENVIRONMENT`.

**Step 3: Update the environment template**

Document endpoint, public key, secret key, and environment placeholders. Keep `HARNESS_OTEL_ENABLED=false` as the default.

**Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/deploy/test_docker_assets.py -q
```

Expected: all Docker asset tests pass.

**Step 5: Commit**

```bash
git add deploy/otel-collector/collector.yaml deploy/docker-compose/compose.yaml deploy/docker-compose/.env.docker.example tests/unit/deploy/test_docker_assets.py
git commit -m "feat: configure external Langfuse in Compose"
```

### Task 3: Export a Langfuse-compatible environment resource attribute

**Files:**

- Modify: `tests/integration/test_trace_propagation.py`
- Modify: `src/harness/config.py`
- Modify: `src/harness/observability/provider.py`

**Step 1: Write the failing test**

Build observability with `otel_environment="staging"`, emit a span to the in-memory exporter, and assert the span resource contains:

```python
assert span.resource.attributes["deployment.environment.name"] == "staging"
```

Also assert `service.name` remains unchanged.

**Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/integration/test_trace_propagation.py -q
```

Expected: FAIL because `Settings` has no `otel_environment` and the resource lacks the attribute.

**Step 3: Implement the minimal setting and resource mapping**

Add `otel_environment: str = ""` to `Settings`. When non-empty, add `deployment.environment.name` to the `Resource.create` attributes. Do not add Langfuse SDK dependencies or content-bearing attributes.

**Step 4: Run focused quality checks**

```bash
uv run pytest tests/integration/test_trace_propagation.py -q
uv run ruff check src/harness/config.py src/harness/observability/provider.py tests/integration/test_trace_propagation.py
uv run pyright src/harness/config.py src/harness/observability/provider.py tests/integration/test_trace_propagation.py
```

Expected: all commands pass.

**Step 5: Commit**

```bash
git add src/harness/config.py src/harness/observability/provider.py tests/integration/test_trace_propagation.py
git commit -m "feat: label external Langfuse environments"
```

### Task 4: Update operator documentation

**Files:**

- Modify: `docs/deployment.md`
- Modify: `docs/local-development.md`
- Modify: `README.md`

**Step 1: Document the optional flow**

Explain:

- normal `docker-up` leaves export disabled;
- `docker-up-observability` requires endpoint/public key/secret key;
- Cloud regions and external self-hosted endpoints use `/api/public/otel`;
- `LANGFUSE_ENVIRONMENT` controls trace environment filtering;
- Langfuse supports OTLP/HTTP, not OTLP/gRPC;
- secrets stay in the Collector, and `.env.docker` is ignored.

**Step 2: Validate documentation and configuration**

```bash
git diff --check
docker compose --env-file deploy/docker-compose/.env.docker -f deploy/docker-compose/compose.yaml config --quiet
docker compose --env-file deploy/docker-compose/.env.docker -f deploy/docker-compose/compose.yaml --profile observability config --quiet
```

Expected: no formatting or Compose interpolation errors.

**Step 3: Commit**

```bash
git add README.md docs/deployment.md docs/local-development.md
git commit -m "docs: explain optional external Langfuse export"
```

### Task 5: Validate the Collector and full repository

**Files:**

- No production edits expected.

**Step 1: Validate Collector startup/config parsing**

Run the pinned Collector image with placeholder endpoint/public/secret values and the repository config mounted read-only. Confirm it starts without configuration errors, then stop it without sending credentials externally.

**Step 2: Run the full Python checks**

```bash
make verify
```

Expected: Ruff, Pyright, and all Python tests pass.

**Step 3: Run Web checks**

```bash
cd web/harness-console
npm test
npm run build
```

Expected: all Vitest tests and the Next.js production build pass.

**Step 4: Inspect repository state**

```bash
git diff --check
git status -sb
```

Expected: clean worktree on `feature/phase-1`.

### Task 6: Publish the update

**Files:**

- No file edits expected.

**Step 1: Push the current branch**

```bash
git push origin feature/phase-1
```

**Step 2: Update Draft PR #1 description if needed**

Add external Langfuse endpoint/public/secret/environment configuration and Collector Basic Auth validation to the PR summary and validation section.

**Step 3: Verify the remote state**

```bash
gh pr view 1 --repo PrayforH/agent-harness --json url,isDraft,headRefName,baseRefName
```

Expected: Draft PR #1 remains open from `feature/phase-1` to `main`.
