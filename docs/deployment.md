# Docker deployment

仓库提供可直接验证的生产形态 Compose：FastAPI、独立 Worker、Next.js standalone Web、PostgreSQL、Redis、MinIO、Alembic migration、种子 Agent，以及可选的 OTel Collector → Langfuse 链路。

## 1. 准备配置

```bash
cp deploy/docker-compose/.env.docker.example deploy/docker-compose/.env.docker
```

至少替换以下值：

- `POSTGRES_PASSWORD`
- `MINIO_ROOT_PASSWORD`
- `HARNESS_NEW_API_BASE_URL`
- `HARNESS_NEW_API_KEY`
- `HARNESS_NEW_API_MODEL`

`HARNESS_NEW_API_*` 接受 Anthropic-compatible 网关，包括 new-api。凭据只通过容器环境注入，不应写进镜像或提交到 Git。

如果网关运行在 Docker 宿主机：

- macOS/Windows Docker Desktop 或 Colima 通常使用 `http://host.docker.internal:<port>`；
- 网关绑定局域网地址时，可直接填写容器可访问的 LAN 地址；
- 宿主机只监听 `127.0.0.1` 且没有 `host.docker.internal` 转发时，容器无法连接，需要调整监听地址或网络配置。

## 2. 国内依赖镜像

示例配置默认使用：

```dotenv
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
```

它们分别用于 Python/uv 与 Node/npm 的镜像构建阶段，可在 `.env.docker` 中覆盖。Docker 基础镜像（Python、Node、PostgreSQL 等）的拉取由 Docker daemon 控制；如网络受限，应另行给 Docker/Colima 配置 registry mirror，或预先导入基础镜像。

## 3. 构建并启动

```bash
make docker-config
make docker-build
make docker-up
```

也可以直接执行：

```bash
docker compose \
  --env-file deploy/docker-compose/.env.docker \
  -f deploy/docker-compose/compose.yaml \
  up -d --build --wait
```

启动顺序由健康检查控制：PostgreSQL → migration，MinIO → bucket 初始化，然后 API/Worker → seed → Web。默认入口：

- Web：<http://127.0.0.1:3000>
- API：<http://127.0.0.1:8000>
- API 健康检查：<http://127.0.0.1:8000/healthz>
- MinIO Console：<http://127.0.0.1:9001>

## 4. 黑盒验收

模型网关支持 Anthropic streaming、tool use 和 Claude Agent SDK 所需协议时，运行：

```bash
make docker-e2e
```

验收覆盖：Agent 发布、浏览器式文件上传、输入预处理和 lineage、真实 SDK 文件读取、策略工具门、跨 Session 用户记忆、Artifact 发布与下载、AG-UI 终态，以及 API/Worker 重启后的 PostgreSQL/MinIO 持久性。

## 5. Langfuse 可观测性

在 `.env.docker` 中配置：

```dotenv
HARNESS_OTEL_ENABLED=true
LANGFUSE_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
LANGFUSE_AUTHORIZATION=Basic <base64(public-key:secret-key)>
```

然后启动 observability profile：

```bash
make docker-up-observability
```

应用只发送 OTLP/HTTP 到本地 Collector；Collector 使用 `deploy/otel-collector/collector.yaml` 转发到 Langfuse。Trace 属性会经过 Harness 脱敏，不记录模型密钥和原始上传内容。

## 6. 停止与数据

```bash
make docker-down
```

该命令保留 PostgreSQL、Redis 和 MinIO named volumes。需要清空验证数据时显式执行：

```bash
docker compose \
  --env-file deploy/docker-compose/.env.docker \
  -f deploy/docker-compose/compose.yaml \
  down -v
```

## 生产边界

Compose 是单机生产形态与集成验证基线，不等于完整公网部署方案。正式环境仍应在反向代理或 API Gateway 中完成身份认证、TLS、限流和可信身份头注入；运行不受信任 Agent 时应把 `HARNESS_SANDBOX_PROVIDER` 切换为 Daytona 等隔离执行环境，而不是使用容器内 local workspace。
