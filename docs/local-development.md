# Local development

## Prerequisites

- Python 3.12、uv
- Docker + Compose
- Node.js 20+、npm

## Start and stop

```bash
make dev-up
make dev-down
```

`dev-up` 会启动 PostgreSQL 17、Redis 7、MinIO，执行 Alembic，随后启动 API 和 Next.js 控制台，并幂等发布 `echo-agent@0.1.0`。日志位于 `work/api.log` 与 `work/web.log`。为方便 Web 验证，它仅在本地启动命令中设置 `HARNESS_LOCAL_AUTO_EXECUTE=true`；测试和默认配置仍为显式 Worker 驱动。

如果本机 Docker 配置引用了缺失的 `docker-credential-osxkeychain`，脚本只对本次公共镜像拉取临时使用仓库内的匿名 helper，不修改全局 Docker 配置。

## Local services

| Service | URL | Credentials |
|---|---|---|
| API | `http://127.0.0.1:8000` | local identity headers |
| Web UI | `http://127.0.0.1:3000` | none |
| PostgreSQL | `localhost:5432/harness` | `harness / harness` |
| Redis | `localhost:6379` | none |
| MinIO API | `localhost:9000` | `minioadmin / minioadmin` |
| MinIO Console | `http://localhost:9001` | same |

Langfuse 和 OTel Collector 不在本地 Compose 中，也不是启动前提。

## Web interaction validation

打开 `http://127.0.0.1:3000` 后，默认界面是 CopilotKit v2 全页 Chat。浏览器只连接同源 `/api/copilotkit`；Next.js BFF 在服务端注入 `X-Tenant-ID`、`X-User-ID`，这些身份头不会进入浏览器配置或 URL。

验证普通流式回答：

```text
请简要说明这个 Harness
```

验证审批、自动恢复与 Artifact：

```text
[approval] [artifact] 验证完整流程
```

预期流程：

1. 对话先显示 Fake Runtime 的回答和审批卡片。
2. 点击“批准并继续”，同一 SSE 收到审批结果并自动恢复 Run。
3. 对话显示 `result.txt` 产物卡片；“下载”经 `/api/harness/artifacts/:id` 鉴权代理。
4. 刷新后 thread ID 保持不变，CopilotRuntime connect 回放消息和领域卡片。
5. “运行详情”默认关闭；打开后使用 CopilotKit Inspector 查看 AG-UI 事件、消息与状态。

“新对话”会生成并持久化新的 thread ID。开发者详情不显示 tenant/user 身份头。

## Observability and Langfuse

本地保持：

```dotenv
HARNESS_OTEL_ENABLED=false
HARNESS_OTLP_ENDPOINT=
```

生产环境建议让应用输出到自建 Collector，再由 `deploy/otel-collector/collector.yaml` 转发到 Langfuse。当前 Langfuse 官方 OTLP 入口为 `/api/public/otel`，使用 Basic Auth，且只支持 OTLP/HTTP；模板也包含实时摄取所需的 `x-langfuse-ingestion-version: 4`。

Collector 环境变量示例：

```dotenv
LANGFUSE_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
LANGFUSE_AUTHORIZATION=Basic <base64(public-key:secret-key)>
```

## Common commands

```bash
make migrate
make verify
make e2e
make web-test
make web-build
```

## Troubleshooting

- 端口占用：检查 `5432/6379/9000/9001/8000/3000`。
- 容器未就绪：运行 `uv run python scripts/wait_for_local_services.py`。
- API/Web 退出：查看 `work/*.log`，删除陈旧的 `work/*.pid` 后重启。
- bootstrap 提示 SOCKS 依赖：确认使用仓库最新脚本；本地 bootstrap 显式 `trust_env=false`，不会把 loopback 请求发送到系统代理。
- new-api 只返回文本但工具失败：网关必须兼容 Anthropic streaming 与 tool use；Manifest 的 required capabilities 会阻止不兼容路由。
- 不要将 `.env`、模型 key 或 Langfuse secret 提交；所有事件与 trace 属性都应先经过脱敏。
