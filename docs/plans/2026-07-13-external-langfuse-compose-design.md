# 外部 Langfuse Compose 适配设计

日期：2026-07-13

状态：已确认

范围：外部 Langfuse Cloud 或外部自托管 Langfuse；不在 Harness Compose 内部署 Langfuse

## 1. 目标

将现有的可选 OpenTelemetry Collector 出口完善为可直接配置的 Langfuse 集成。默认 Harness 不启动 Collector、不导出 Trace；启用 `observability` profile 后，API 与 Worker 将 OTLP/HTTP Trace 发给 Compose 内 Collector，再由 Collector 转发到外部 Langfuse。

用户只需配置 Langfuse endpoint、public key、secret key 和 environment，不再手工拼接或 Base64 编码 Authorization header。

## 2. 方案选择

### 2.1 采用：Collector Basic Auth 扩展

Collector 使用 `basicauth/client` 扩展，以 `LANGFUSE_PUBLIC_KEY` 作为 username、`LANGFUSE_SECRET_KEY` 作为 password。`otlphttp/langfuse` exporter 引用该扩展，并固定添加 `x-langfuse-ingestion-version: 4`。

优点：

- 密钥仍只存在于 Collector 环境，不进入 API/Worker。
- 不要求用户计算 `Basic <base64(public:secret)>`。
- 保留 Collector 的批处理、内存限制、重试和未来采样扩展点。
- Cloud 与外部自托管 Langfuse 使用同一套配置。

### 2.2 不采用：预编码 Authorization

现有 `LANGFUSE_AUTHORIZATION` 虽然简单，但容易因换行、shell 差异或遗漏 `Basic ` 前缀而配置错误，也不利于 Secret 管理系统分别注入 public/secret key。

### 2.3 不采用：应用直连 Langfuse

让 API/Worker 各自持有 Langfuse 密钥并直连 endpoint 会重复配置，并失去 Collector 作为统一出口的批处理与故障隔离价值。

## 3. 配置模型

`.env.docker` 增加以下外部配置：

```dotenv
HARNESS_OTEL_ENABLED=false
LANGFUSE_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
LANGFUSE_PUBLIC_KEY=pk-lf-replace-me
LANGFUSE_SECRET_KEY=sk-lf-replace-me
LANGFUSE_ENVIRONMENT=production
```

约束：

- `LANGFUSE_OTLP_ENDPOINT` 必须指向基础 OTLP endpoint，即以 `/api/public/otel` 结尾；Collector exporter 会追加 `/v1/traces`。
- Langfuse Cloud 与版本不低于 v3.22 的外部自托管实例均可使用该入口。
- Langfuse 当前只支持 OTLP/HTTP；API/Worker 到 Collector 可以继续使用 OTLP/HTTP。
- `LANGFUSE_ENVIRONMENT` 使用 Langfuse 支持的小写环境名，例如 `production`、`staging`、`local`。

## 4. Compose 与数据流

```text
API / Worker
  HARNESS_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
        │ OTLP/HTTP
        ▼
OTel Collector (profile: observability)
  memory_limiter → batch → otlphttp/langfuse
        │ Basic(public key, secret key)
        │ x-langfuse-ingestion-version: 4
        ▼
External Langfuse /api/public/otel/v1/traces
```

默认 `HARNESS_OTEL_ENABLED=false`，因此普通 `docker compose up` 不依赖 Collector。启用时使用现有 `make docker-up-observability`，同时设置 `HARNESS_OTEL_ENABLED=true`。

Collector 端口只绑定到宿主机 loopback，避免无意暴露 OTLP 接收端口。API 与 Worker 通过 Compose 内部网络访问服务名。

## 5. Langfuse 映射

Harness 保持 OpenTelemetry-first，不引入 Langfuse SDK。Collector 转发标准 Span；应用资源属性增加 `langfuse.environment`，用于 Langfuse 环境筛选。现有 Run、Sandbox、Workspace、Model 和 Tool span 层级保持不变，敏感数据继续在进入 exporter 前脱敏。

本次不把 prompt、工具完整输出或附件内容写入 Span，也不新增 Langfuse Prompt Management、Dataset、Score 或 Trace URL 反向查询。

## 6. 错误与安全

- 缺少 endpoint/public key/secret key 时，Compose 在启用 observability profile 时应配置失败，而默认 profile 不受影响。
- Collector 无法连接 Langfuse 时，由 exporter 重试和队列行为处理；Agent Run 不因外部可观测端点不可用而失败。
- `.env.docker` 保持 Git ignore，示例文件只包含非功能占位符。
- Collector 日志与 Compose 输出不得打印 secret key。

## 7. 验证

- 解析 Collector YAML，验证 `basicauth/client`、OTLP/HTTP exporter、ingestion v4 header 和 extension 注册。
- 解析 Compose，验证 `observability` profile、三项 Langfuse连接配置、loopback 端口和环境属性。
- 分别验证默认 profile 与 observability profile 的 `docker compose config`。
- 使用 Collector 镜像执行配置校验；无需真实 Langfuse 凭据。
- 运行现有 Python、Web 与 Docker 配置测试，确保默认禁用路径无回归。

## 8. 官方依据

- Langfuse OpenTelemetry endpoint：<https://langfuse.com/integrations/native/opentelemetry>
- OpenTelemetry Collector Basic Auth extension：<https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/extension/basicauthextension>
