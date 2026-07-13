# Claude Agent Harness

一个以 Claude Agent SDK 为执行内核、面向后续 Agent 产品开发的基础 Harness。它把 Agent 定义、运行、审批、持久化、模型网关、事件协议和 Web 验证面从业务 Agent 中拆开。

## 这套 Harness 的价值

- **让 Agent 代码只关注业务能力。** Manifest 固化 prompt、tools、skills、subagents、权限和预算；平台负责 Session、Run、Workspace、Artifact 与失败恢复。
- **保留 Claude Agent SDK 的能力边界。** 直接使用官方 SDK、SessionStore 和消息类型，不用 LangGraph 重写 Claude Code 的执行语义。
- **new-api 可以作为优先模型网关。** 通过 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_AUTH_TOKEN` 注入 Anthropic-compatible 网关；能力不满足时只走 Manifest 明确声明的官方回退，绝不静默切换。
- **复杂 Agent 可安全落地。** 工具调用经过 `allow / deny / ask` 策略，审批可暂停、过期、拒绝或恢复；Run 有幂等键、状态机和 fencing token。
- **从单机验证平滑走向生产。** 核心依赖端口抽象；本地用 Fake Runtime/内存组合，持久化契约已在 PostgreSQL、Redis、MinIO 上验证。
- **前后端协议解耦。** Harness 事件是权威事实，AG-UI 只是无状态投影；assistant-ui 控制台可以替换，而不会影响 Agent 执行层。
- **可观测但不绑定厂商。** 应用只发 OpenTelemetry；生产可由 Collector 输出到 Langfuse，本地默认完全关闭 exporter。

这意味着后续开发一个新 Agent，主要工作变成“写 Manifest + prompt/skills/tools + 少量 Python 扩展”，而不是每次重建会话、审批、网关、事件流、存储和 UI。

## 快速开始

```bash
uv sync --group dev
uv run harness agent init invoice-reviewer
uv run harness agent validate agents/invoice-reviewer/agent.yaml
cd web/harness-console && npm install && cd ../..
make dev-up
```

领域 Agent 的 prompt、Python Tool、外部 MCP、发布与评测流程见 [docs/domain-agents.md](docs/domain-agents.md)。

使用 cc-switch 当前已应用的 Claude Provider 启动真实模型模式：

```bash
make dev-up-cc-switch
```

该命令只在 API 启动时读取 `~/.claude/settings.json`，不会把网关令牌写入项目。cc-switch 切换 Provider 后需要重启 Harness。

打开：

- Harness API / Swagger: <http://127.0.0.1:8000/docs>
- Harness Console: <http://127.0.0.1:3000>
- MinIO Console: <http://127.0.0.1:9001>

本地栈只有 PostgreSQL、Redis、MinIO；**不包含 Langfuse 或 OTel Collector**。`make dev-up` 会显式设置 `HARNESS_OTEL_ENABLED=false`。

## 验证

```bash
make verify
make e2e
make web-test
make web-build
```

无模型密钥的 E2E 会验证：Manifest 发布、Session/Run、SSE/AG-UI、工具审批、恢复、Artifact 下载与哈希、终态成功，以及本地 OTel exporter 关闭。

Web 首页直接使用 assistant-ui 的 Thread、Composer、Attachment 与 Markdown primitives，并通过官方 AG-UI runtime adapter 连接 Harness。主对话以紧凑执行时间线呈现工作摘要、工具和子 Agent，JSON/代码/Diff 使用结构化卡片；“运行详情”提供 Harness 事件脊柱与模型、Provider、时长、轮次、成本、停止原因。`make dev-up` 使用 Fake Runtime；`make dev-up-cc-switch` 使用当前 cc-switch Provider。两种模式都会幂等发布 `helper@1.0.0` 与 `echo-agent@0.1.0`，打开页面后可直接输入普通问题。以下审批与产物标记仅用于 Fake Runtime 验收：

```text
[approval] [artifact] 验证完整流程
```

审批卡片选择“批准并继续”后，同一 Run 自动恢复并显示 `result.txt` 下载卡片。页面刷新会复用本地 thread ID 且不会重复创建 Run；Phase 1 尚未把耐久事件接成 assistant-ui 的历史消息 adapter，因此刷新后不会自动恢复聊天正文。原始 AG-UI 活动、消息和状态可在“运行详情”中核对。

点击“＋ 文件”上传本地文件后，Next.js 同源 BFF 会创建 InputArtifact；消息发送时只携带服务端 ID。Worker 校验归属后将文件以只读方式挂载到本次 Run 的 `inputs/`，Claude Agent SDK 可使用 `Read` 读取。浏览器路径、内联字节和伪造 URL 不会被信任为工作区输入。

真实模式可用下列问题验证子 Agent：

```text
必须调用 Agent/Task 工具委派 helper 子 Agent，用一句话确认收到任务；等待完成后给最终答案。
```

输入 `[slow] 验证停止` 并在消息开始后点击停止按钮，可以验证浏览器流中止、同源 AG-UI BFF 取消映射及 Harness Run 最终进入 `cancelled` 的完整链路。

new-api 实际连通性是显式的可选 smoke：

```bash
NEW_API_BASE_URL=https://gateway.example/api \
NEW_API_KEY=... \
NEW_API_MODEL=claude-sonnet-4-6 \
uv run python scripts/smoke_new_api.py
```

未提供三个变量时脚本安全跳过。详细说明见 [docs/local-development.md](docs/local-development.md)。

## 当前边界

Phase 1 是可运行的基础框架与验证面，不是最终控制平面：生产认证、Kubernetes per-run Pod、完整数据库组合根、配额/计费和长期事件订阅仍应在后续阶段实现。主 Agent 已能解析 builtin、Python SDK MCP 和服务端注册的外部 MCP，并通过 `PreToolUse` 在真实 SDK 执行前完成策略与审批；subagent 自定义工具、字段级工具参数脱敏和多进程持久化审批 continuation 仍是明确的后续边界。
