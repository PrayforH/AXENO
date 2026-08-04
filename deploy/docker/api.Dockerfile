ARG KUBECTL_IMAGE=registry.k8s.io/kubectl:v1.33.1
ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm
FROM ${KUBECTL_IMAGE} AS kubectl

FROM ${PYTHON_IMAGE} AS builder

WORKDIR /app

ARG UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
RUN python -m pip install --no-cache-dir \
    --index-url "${UV_DEFAULT_INDEX}" \
    "uv==0.11.28"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}

COPY pyproject.toml uv.lock README.md ./
RUN uv export \
    --frozen \
    --no-dev \
    --no-hashes \
    --no-emit-project \
    --output-file /tmp/requirements.txt \
    && python -m venv .venv \
    && .venv/bin/pip install --no-cache-dir \
        --index-url "${UV_DEFAULT_INDEX}" \
        --requirement /tmp/requirements.txt

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY agents ./agents
COPY scripts/seed_docker.py ./scripts/seed_docker.py
RUN .venv/bin/pip install --no-cache-dir \
    --index-url "${UV_DEFAULT_INDEX}" \
    --no-deps \
    .

FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 harness \
    && useradd --system --uid 10001 --gid harness --home-dir /app harness

WORKDIR /app
COPY --from=builder --chown=harness:harness /app/.venv /app/.venv
COPY --from=builder --chown=harness:harness /app/src /app/src
COPY --from=builder --chown=harness:harness /app/migrations /app/migrations
COPY --from=builder --chown=harness:harness /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=harness:harness /app/agents /app/agents
COPY --from=builder --chown=harness:harness /app/scripts /app/scripts
COPY --from=kubectl /bin/kubectl /usr/local/bin/kubectl
COPY --chown=harness:harness deploy/docker/entrypoint-api.sh /usr/local/bin/entrypoint-api
COPY --chown=harness:harness deploy/docker/entrypoint-worker.sh /usr/local/bin/entrypoint-worker

USER harness
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

ENTRYPOINT ["entrypoint-api"]
