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

连接 cc-switch 当前 Claude Provider：

```bash
make dev-up-cc-switch
```

真实模式在 API 启动时读取 `~/.claude/settings.json` 中的 Anthropic endpoint、model 和 credential。凭据不会复制到仓库文件或日志；cc-switch 切换 Provider 后执行 `make dev-down && make dev-up-cc-switch`。

`dev-up` 会启动 PostgreSQL 17、Redis 7、MinIO，执行 Alembic，随后启动 API 和 Next.js 控制台，并幂等发布 `echo-agent@0.1.0`。日志位于 `work/api.log` 与 `work/web.log`。为方便 Web 验证，它仅在本地启动命令中设置 `HARNESS_LOCAL_AUTO_EXECUTE=true`；测试和默认配置仍为显式 Worker 驱动。`dev-up-cc-switch` 只额外选择 `claude-sdk` Runtime，不会在配置缺失时回退 Fake Runtime。

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

打开 `http://127.0.0.1:3000` 后，默认界面是 assistant-ui 全页 Chat。浏览器只连接同源 `/api/agui` 与 `/api/input-artifacts`；Next.js BFF 在服务端注入 `X-Tenant-ID`、`X-User-ID`，这些身份头不会进入浏览器配置或 URL。

聊天中的“执行进度”以紧凑时间线显示模型路由、工作摘要、工具与子 Agent；工具输入/输出会按 JSON、代码或 unified diff 自动格式化。点击“运行详情”会打开右侧 Run Inspector，展示 Harness 事件脊柱、模型、Provider、时长、轮次、成本与停止原因。

点击“＋ 文件”可上传浏览器可访问的本地文件。上传先创建 InputArtifact；发送消息后，Worker 校验租户和用户归属，再把文件只读挂载到该 Run 的 `inputs/`。SDK 读取输入文件产生的原始内容不会写入耐久工具事件。

验证普通流式回答：

```text
请简要说明这个 Harness
```

真实 `claude-sdk` 模式下验证工具与子 Agent：

```text
必须调用 Agent/Task 工具委派 helper 子 Agent，用一句话确认收到任务；等待完成后给最终答案。
```

预期出现 `Agent` 子 Agent 卡片、`subagent.started/completed` 时间线，以及成功终态；子 Agent 的部分文本不会混入主 Agent 的流式消息。SDK 内部协调字段（如 `agentId`、`output_file`）不会进入界面。

验证停止生成与后端取消：

```text
[slow] 验证停止
```

消息开始生成后点击输入框旁的停止按钮。前端会中止当前流，同时通知 Harness 取消对应的内部 Run；约 3 秒内后端状态应从 `cancelling` 进入 `cancelled`，且不会继续输出剩余内容。`[slow]` 只是 Fake Runtime 的本地验收标记，不会进入真实 Agent 协议。

验证审批、自动恢复与 Artifact：

```text
[approval] [artifact] 验证完整流程
```

预期流程：

1. 对话先显示 Fake Runtime 的回答和审批卡片。
2. 点击“批准并继续”，同一 SSE 收到审批结果并自动恢复 Run。
3. 对话显示 `result.txt` 产物卡片；“下载”经 `/api/harness/artifacts/:id` 鉴权代理。
4. 刷新后 thread ID 保持不变，且不会重复创建 Run；Phase 1 暂不自动恢复聊天正文。
5. “运行详情”默认关闭；打开后查看结构化 Run Inspector 与原始 Harness 活动。

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
uv run harness agent init invoice-reviewer
uv run harness agent validate agents/invoice-reviewer/agent.yaml
make migrate
make verify
make e2e
make web-test
make web-build
```

完整领域开发流程见 [domain-agents.md](domain-agents.md)。本地 API 的默认 MCP Registry 为空；领域 Manifest 使用 `mcp:` 前，必须在服务端组合根注册对应逻辑 ID。真实 SDK 已通过 `PreToolUse` 前置执行策略；本地 inline 审批 waiter 只适用于单 API 进程。

## Troubleshooting

- 端口占用：检查 `5432/6379/9000/9001/8000/3000`。
- 容器未就绪：运行 `uv run python scripts/wait_for_local_services.py`。
- API/Web 退出：查看 `work/*.log`，删除陈旧的 `work/*.pid` 后重启。
- bootstrap 提示 SOCKS 依赖：确认使用仓库最新脚本；本地 bootstrap 显式 `trust_env=false`，不会把 loopback 请求发送到系统代理。
- new-api 只返回文本但工具失败：网关必须兼容 Anthropic streaming 与 tool use；Manifest 的 required capabilities 会阻止不兼容路由。
- 不要将 `.env`、模型 key 或 Langfuse secret 提交；所有事件与 trace 属性都应先经过脱敏。
