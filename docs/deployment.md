# Docker deployment

认证、可选 Google/GitHub SSO、RBAC 与生产安全配置见
[authentication.md](authentication.md)。

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
- `HARNESS_API_BEARER_TOKEN`（至少 32 个随机字符）
- `HARNESS_NEW_API_COMPATIBILITY`
- `HARNESS_NEW_API_CAPABILITIES`
- `HARNESS_SANDBOX_PROVIDER`（`daytona`、`e2b`、`kubernetes` 或显式不安全的 `local`）
- `HARNESS_SANDBOX_EXECUTION_MODE`：`remote_cli` 让 Claude CLI 在沙箱中运行；
  `worker_cli_deferred` 让 CLI 常驻 Worker，首次文件或 Bash 工具调用时才创建远端沙箱，
  可显著降低纯对话首 Token 延迟

`HARNESS_NEW_API_*` 直接连接 Anthropic-compatible 网关，包括 new-api；生产链路不依赖 cc-switch。凭据只通过容器环境注入，不应写进镜像或提交到 Git。`HARNESS_API_BEARER_TOKEN` 用于 Web BFF、seed、E2E 与 API 之间的服务认证，不进入浏览器 bundle。`COMPATIBILITY` 可取 `full/degraded/unsupported`，`CAPABILITIES` 是逗号分隔的已验证能力（例如 `streaming,tool_use`）。只声明实际通过 `uv run python scripts/smoke_new_api.py` 黑盒验证的能力；Manifest 要求的能力不在该集合时，Run 会在模型请求前 fail closed。

如需在 Manifest 使用 `fallbackRoute`，同时配置 `HARNESS_ANTHROPIC_BASE_URL`、`HARNESS_ANTHROPIC_API_KEY` 与 `HARNESS_ANTHROPIC_MODEL`。主 new-api 路由不满足能力画像时才会切换；未配置官方回退时会返回明确的配置冲突，不会静默改用其他模型。

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

启动顺序由健康检查控制：PostgreSQL → migration，MinIO → bucket 初始化，然后 API/Worker → seed → Web。seed 会先把 `helper-agent`、`echo-agent` 和 `public-opinion-agent` 构建成可复现 bundle，再通过生产 bundle API 幂等发布；生产 API 不接受服务器本地路径。默认入口：

- Web：<http://127.0.0.1:3000>
- API：<http://127.0.0.1:8000>
- API 健康检查：<http://127.0.0.1:8000/healthz>
- MinIO Console：<http://127.0.0.1:9001>

### 切换到舆情 Agent

控制台当前按部署配置固定一个 Agent，不在浏览器中动态修改生产绑定。编辑忽略提交的 `deploy/docker-compose/.env.docker`：

```dotenv
HARNESS_AGENT_NAME=public-opinion-agent
HARNESS_AGENT_VERSION=0.1.1
HARNESS_MCP_SECRET_REFERENCES_JSON={"tavily-readonly":{"api_key":"TAVILY_API_KEY"}}
HARNESS_MCP_SERVER_SECRETS_JSON={"TAVILY_API_KEY":"replace-with-tavily-api-key"}
```

然后幂等发布三个依赖包，并只重建读取这些环境变量的服务：

```bash
docker compose --env-file deploy/docker-compose/.env.docker \
  -f deploy/docker-compose/compose.yaml run --rm seed
docker compose --env-file deploy/docker-compose/.env.docker \
  -f deploy/docker-compose/compose.yaml up -d --force-recreate worker web
```

在页面中新建对话后生效；已经存在的 Session 继续绑定创建时的 Agent 版本。Tavily token 只进入 Worker，不会进入 API、Web 或浏览器。`public-opinion-agent` 不是未经修改的模板产物，而是按相同脚手架契约迁移并补全了舆情 prompt、Skill、只读 MCP、输出规范和评测集的领域参考实现。

## 4. 黑盒验收

模型网关支持 Anthropic streaming、tool use 和 Claude Agent SDK 所需协议时，运行：

```bash
make docker-e2e
```

验收覆盖：Agent 发布、浏览器式文件上传、输入预处理和 lineage、真实 SDK 文件读取、策略工具门、Daytona `outputs/` 自动 Artifact、同 Session workspace 恢复、AG-UI 终态，以及 API/Worker 重启后的 PostgreSQL/MinIO 持久性。远端 Daytona 不把 worker 内的 Python memory SDK MCP 伪装成可用能力。

## 5. Langfuse 可观测性

在 `.env.docker` 中配置：

```dotenv
HARNESS_OTEL_ENABLED=true
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_PROJECT_ID=replace-with-project-id
LANGFUSE_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
LANGFUSE_PUBLIC_KEY=pk-lf-replace-me
LANGFUSE_SECRET_KEY=sk-lf-replace-me
LANGFUSE_ENVIRONMENT=production
HARNESS_OTEL_CONTENT_CAPTURE=off
HARNESS_OTEL_CONTENT_MAX_CHARS=12000
```

然后启动 observability profile：

```bash
make docker-up-observability
```

Web、API 和 Worker 都只发送 OTLP/HTTP 到本地 Collector；Collector 使用 `deploy/otel-collector/collector.yaml` 的 Basic Auth extension 将公钥和私钥转成认证头，并携带 `x-langfuse-ingestion-version: 4` 转发到 Langfuse。应用容器不会收到 Langfuse 密钥。Web 在用户提交问题时创建 `harness.web.question`，通过 W3C `traceparent`/`tracestate` 传给 API；API 的 `harness.api.request` 提取该上下文，创建 Run 时继续注入 Worker；Worker 再覆盖沙箱、记忆、模型、MCP、工具、审批、制品和清理阶段。持久化 Run Event 同时记录当时的 `trace_id` 与 `span_id`，用于事件回放和 Trace 互相定位。

Langfuse 只接受 OTLP/HTTP；`LANGFUSE_OTLP_ENDPOINT` 应填写外部 Langfuse 实例的 `/api/public/otel` 基础入口，Exporter 会追加 `/v1/traces`。`LANGFUSE_BASE_URL` 和 `LANGFUSE_PROJECT_ID` 仅提供给 Web 容器，用于右侧运行面板跳转到对应项目的 Trace 搜索页，不包含摄取密钥。自托管实例需要支持该 OTel 入口。Trace Resource 使用 `LANGFUSE_ENVIRONMENT` 写入 `deployment.environment.name`，内容仍经过 Harness 脱敏，不记录模型密钥、原始 prompt、模型响应和上传内容。

一次 Run 对应一个分布式 Trace；同一网页对话的多个 Run 使用 `langfuse.session.id` 聚合。`harness.model.run` 提供 Agent 版本、运行时内容哈希、package hash、Provider、模型、route、Policy Profile、Skill 数量、轮次、耗时、成本和白名单化 Token 计数等低敏检索维度。默认不输出 prompt、模型响应或 Provider 原始 usage 数据；只有下述显式内容观测开关可以增加脱敏后的问题与回答。

内容观测由 `HARNESS_OTEL_CONTENT_CAPTURE` 显式控制。默认值 `off` 在所有环境都不导出问题和回答；仅在受控调试环境设置为 `redacted` 时，才会把经过凭据脱敏且受 `HARNESS_OTEL_CONTENT_MAX_CHARS` 限制的问题和最终回答映射为 Langfuse Trace/Observation 的 input 与 output。不存在绕过脱敏的 raw 模式。生产环境应保持 `off`，工具读取结果和上传文件正文无论何种模式都不会作为 Trace 内容导出。

未启用 `observability` profile 时 Collector 不启动，`make docker-up` 不要求任何 Langfuse 配置。宿主机 OTLP 端口只绑定 `127.0.0.1`。

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

Compose 是单机生产形态与集成验证基线，不等于完整公网部署方案。API 的 `/v1` 边界必须通过服务 Bearer 校验，`/healthz` 保持匿名可探活；不要把 Bearer 返回给浏览器。当前 Web 使用环境中固定的 tenant/user，适合单租户验证。正式多用户环境仍应在反向代理或 API Gateway 中完成 OIDC、TLS、限流，并由受信 BFF 根据登录态注入 tenant/user，不能接受浏览器自报身份头。生产默认要求 Daytona 等强隔离；`local` 只允许受信的单机验证，并且必须显式设置 `HARNESS_ALLOW_UNSAFE_LOCAL_SANDBOX=true` 承认风险。

Compose 将控制面与执行面凭据分开：只有 worker 接收模型网关、Daytona 和 MCP secret；API 只接收服务 Bearer、DB/Redis/MinIO 与 OTel 配置，migration 只接收数据库 URL。不要为了排障把 worker 的执行环境整块复制给 API、Web 或 migration。

Worker 队列使用 Redis visibility lease：dequeue 后进入 processing，执行期间每 20 秒续租，成功后 ack，异常按延迟 retry；worker 崩溃后租约到期的任务会重新进入 ready。每次交付都有独立 receipt，旧 worker 的迟到 ack 不能删除新 owner 的 lease；Run Repository 同时用 fencing token 拒绝旧 owner 的迟到写入。`HARNESS_WORKER_TASK_HEARTBEAT_SECONDS` 必须小于 `HARNESS_WORKER_TASK_VISIBILITY_TIMEOUT_SECONDS`。这保证“至少一次交付”，业务写工具仍必须幂等，不能依赖队列做到恰好一次。

Studio Preview 会在目标 Sandbox 内执行版本化 Live Preflight：模型流式与 Tool Use、MCP
initialize/tools-list/审核过的只读 smoke、Workspace 文件操作、审批策略和 Artifact 回收。整体
超时由 `HARNESS_PREFLIGHT_TIMEOUT_SECONDS` 控制（默认 180 秒）；执行期间 Preview Worker
持续续租，取消、超时或任何阶段失败都会进入稳定终态并执行 Sandbox 清理。Daytona 或目标
网络失败不会回退到 Local Sandbox。

### 耐久 Eval 控制面

Studio Eval 将草稿中的用例固化为不可变 `EvalDatasetVersion`，再对已发布 Agent 版本创建
`EvalRun`。每个 Case 使用独立 Session、稳定幂等键和正常 Run/Event 协议；工具、终态、审批、
输出文本和时长评分只读取服务端持久化事件，不信任浏览器上报结果。

Eval Controller 使用独立 Redis namespace `harness:eval` 做短步 reconcile，并在独立异步控制
循环中与主 Run Worker 并行运行。它不会同步等待子 Run：先持久化 Session/Run 身份并让主 Run
Worker 执行，后续租约再评分和推进下一 Case。因此长 Run 不会阻塞 Eval 超时检查，Worker 或
Controller 重启不会丢失已完成 Case，也不会因单个 Case 基础设施失败终止整套。超时会取消
对应服务端 Run；取消 Eval 会先取消活动 Run，最终收敛到 `cancelled`。
非终态步骤通过当前租约的 retry/reschedule 原子回到 ready，只有终态才 ACK；不要改成先 ACK
再 enqueue，否则进程在两次操作之间退出会遗留无任务的活动 Eval Run。

JSON 与 JUnit 报告写入与 Run Artifact 共用的 MinIO/S3 对象存储，但使用 Eval 自己的元数据和
租户校验下载接口。三张 PostgreSQL 表 `eval_dataset_versions`、`eval_runs`、
`eval_case_results` 由 migration `0009` 创建。晋级控制器必须调用 Eval gate，确认目标版本已通过
所有最新的 required Dataset Version；不得仅依赖 Studio 页面状态。

Daytona 配置通过环境变量注入：

```dotenv
HARNESS_SANDBOX_PROVIDER=daytona
HARNESS_ALLOW_UNSAFE_LOCAL_SANDBOX=false
HARNESS_DAYTONA_API_URL=https://app.daytona.io/api
HARNESS_DAYTONA_API_KEY=dtn_replace_me
HARNESS_DAYTONA_SNAPSHOT=your-approved-snapshot
HARNESS_DAYTONA_REMOTE_WORKSPACE_ROOT=/home/daytona/harness
HARNESS_DAYTONA_CLAUDE_CLI_VERSION=2.1.206
HARNESS_DAYTONA_CLAUDE_CLI_PATH=/home/daytona/.local/bin/claude
HARNESS_DAYTONA_DELETE_ON_DESTROY=true
HARNESS_DAYTONA_AUTO_STOP_INTERVAL_MINUTES=15
HARNESS_DAYTONA_AUTO_DELETE_INTERVAL_MINUTES=60
HARNESS_DAYTONA_SESSION_REUSE_ENABLED=true
HARNESS_DAYTONA_SESSION_IDLE_TIMEOUT_SECONDS=600
HARNESS_DAYTONA_WARM_POOL_MAX_SESSIONS=3
HARNESS_MEMORY_WORKLOAD_TOKEN_SECRET=replace-with-an-independent-32-character-secret
HARNESS_MEMORY_MCP_PUBLIC_URL=https://harness.example.com/mcp/memory/mcp
```

Daytona 容器是 Harness 的强隔离边界：Manifest 已声明的 `Write/Edit` 自动允许，`Bash` 仍需审批。本地 workspace 中 `Write/Edit/Bash` 均需审批。隔离级别来自实际 provision 结果；不得从用户请求或 Agent Manifest 接受该字段。

Daytona 隔离宿主机，但同一 Claude CLI 进程内的 `Bash` 仍可能读取该进程可见的环境变量。Harness 已通过关闭回显的 stdin 帧传入 CLI 参数与环境，避免把系统提示词、模型/MCP secret 写入 Daytona 命令行与 session metadata；但“需要审批”并不等于“凭据不可见”。面向不受信 Agent 时，应进一步使用 Daytona Secrets、域名级出口白名单或凭据注入型 egress proxy，让通用 shell 不直接持有模型网关和业务 MCP 的原始密钥。

Claude SDK 的 `create_sdk_mcp_server()` 保存的是 worker 进程内 Python 对象，不能穿过自定义 Transport 搬到 Daytona。Daytona 模式会拒绝 Manifest 的 `python_entry`，并不注入 worker 本地的 artifact SDK MCP；业务工具应部署为带租户身份认证、可从 sandbox 访问的 HTTP MCP。内置 Memory Bank 是该模式的参考实现：Worker 用独立密钥签发绑定完整 Run 身份、5 分钟有效的令牌，Sandbox 通过 `HARNESS_MEMORY_MCP_PUBLIC_URL` 访问 API 的 `/mcp/memory/mcp`，且只能提议、不能直接写入永久记忆。该密钥不能复用登录 JWT 密钥，公网入口必须使用 TLS 并限制到所需 MCP 路径。内置文件工具仍在 Daytona 内执行，Run 结束时 workspace 会同步回受信控制面；Agent 写入 `outputs/` 的普通文件会在大小、数量和路径复核后自动发布为可下载 Artifact。

从 Daytona 同步回来的 workspace 仍是不可信输入。控制面在归档前重新拒绝 symlink/特殊文件，并限制解压大小、文件总量和归档大小；不要绕过 WorkspaceService 直接把 sandbox 目录挂载或解包到宿主机。

### gVisor / runsc

自托管 Daytona 如果以 gVisor `runsc` 作为底层 OCI runtime，Harness 的 Manifest、SDK Transport、审批和文件同步协议无需改变。部署门禁必须重新验证 Claude CLI、shell/coreutils、CA/DNS、streaming、HTTP MCP、取消、超时和 `outputs/` 收集；依赖 `ptrace`、eBPF、内核模块、特权容器、Docker-in-Docker、部分 FUSE/GPU 或未实现 syscall 的 Agent 应 fail closed。gVisor 也不负责打通内网网关或隔离同一 CLI 进程可见的密钥。

生产 provider 应从可信 provision 结果记录实际 OCI runtime/attestation（例如 `gvisor/runsc`）供审计和 Policy 使用，不能接受 Manifest 或用户请求自报。当前 `container` 隔离级别只表示远端容器边界，不等同于已经证明使用 gVisor；在 attestation 尚未接入前，`Bash` 继续保持审批策略，并按实测冷启动与 I/O 开销重新标定 Run timeout 和队列 lease。

Daytona Cloud 无法访问部署机的 loopback 或未打通路由的私网 new-api 地址；模型网关必须是 sandbox 可达且受 TLS、鉴权和网络策略保护的端点。内网 new-api 应配合同网段/VPN/VPC 内的自托管 Daytona，并分别验证 worker → Daytona API 与 sandbox → new-api 两段网络。部署前运行 `make smoke-daytona`，以一次性 sandbox 完成无模型凭据的连通性探针。

### E2B 公网隔离执行

公网模型与 MCP 无法从 Daytona 出口访问时，可以切换到 E2B：

```dotenv
HARNESS_SANDBOX_PROVIDER=e2b
HARNESS_E2B_API_KEY=secret-reference-value
HARNESS_E2B_TEMPLATE=base
HARNESS_E2B_TIMEOUT_SECONDS=3600
HARNESS_E2B_ALLOW_INTERNET_ACCESS=true
HARNESS_E2B_REMOTE_WORKSPACE_ROOT=/home/user/harness
HARNESS_E2B_CLAUDE_CLI_PATH=/home/user/.local/bin/claude
```

E2B Provider 为每个 Run 创建独立安全沙箱，将 Agent 资产上传到远程工作区，在沙箱内运行固定版本 Claude CLI，结束后收集制品并销毁沙箱。生产密钥只能由服务端环境或 Secret Manager 注入，不得写入 Agent Bundle、Studio Draft 或事件。`allow_internet_access=true` 只代表具备公网出口；可调用的业务能力仍由 Manifest MCP 声明、工具白名单和 Policy 共同约束。

`HARNESS_DAYTONA_CLAUDE_CLI_VERSION` 与当前 Python Agent SDK 捆绑版本保持一致。无 Snapshot 时 Harness 使用 Anthropic 官方安装器在 sandbox 中安装并核验该原生 CLI；生产应在受控 Snapshot 中预装 `HARNESS_DAYTONA_CLAUDE_CLI_PATH`，缩短启动时间并减少运行时供应链依赖。

默认按 `(tenant_id, session_id)` 复用 Harness 自建 sandbox。同一会话串行持有租约，每个 Run 使用独立远端工作目录；结束后清理该目录并把 sandbox 留在 warm pool。空闲超过 `HARNESS_DAYTONA_SESSION_IDLE_TIMEOUT_SECONDS` 或 warm 数超过 `HARNESS_DAYTONA_WARM_POOL_MAX_SESSIONS` 时，维护任务停止并按 `HARNESS_DAYTONA_DELETE_ON_DESTROY` 删除资源。确定性 sandbox 名称允许 Worker 重启后重新连接；失效实例会被丢弃并重建。显式传入的外部 sandbox 不进入共享池，仍只停止、不删除。

远程 Claude 配置目录按租户和 Harness Session 隔离，不放在 Run 工作目录内。CLI 的 `transcript_mirror` 事件会写入 PostgreSQL `SessionStore`；下一轮即使换 Worker、Daytona 实例或 Kubernetes Pod，Transport 也会先把对应转录物化到远端 `CLAUDE_CONFIG_DIR`，再执行 `--resume`。因此 warm sandbox 是性能优化，而不是多轮记忆的唯一持久层。

`HARNESS_DAYTONA_AUTO_STOP_INTERVAL_MINUTES` 应大于会话空闲窗口，推荐至少比 `HARNESS_DAYTONA_SESSION_IDLE_TIMEOUT_SECONDS / 60` 多 5 分钟。自动停止/删除是进程异常后的孤儿资源保险，不替代正常回收。

仅做私网网关的单机黑盒验证时可以临时使用：

```dotenv
HARNESS_SANDBOX_PROVIDER=local
HARNESS_ALLOW_UNSAFE_LOCAL_SANDBOX=true
```

该组合不提供多租户文件系统、进程或网络隔离，不能作为公网生产配置。
