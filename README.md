# Claude Agent Harness

一个以 Claude Agent SDK 为执行内核、面向后续 Agent 产品开发的基础 Harness。它把 Agent 定义、运行、审批、持久化、模型网关、事件协议和 Web 验证面从业务 Agent 中拆开。

## 这套 Harness 的价值

- **让 Agent 代码只关注业务能力。** Manifest 固化 prompt、tools、skills、subagents、权限和预算；平台负责 Session、Run、Workspace、Artifact 与失败恢复。
- **保留 Claude Agent SDK 的能力边界。** 直接使用官方 SDK、SessionStore 和消息类型，不用 LangGraph 重写 Claude Code 的执行语义。
- **new-api 可以作为优先模型网关。** 通过 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_AUTH_TOKEN` 注入 Anthropic-compatible 网关；能力不满足时只走 Manifest 明确声明的官方回退，绝不静默切换。
- **复杂 Agent 可安全落地。** 工具调用经过 `allow / deny / ask` 策略，审批可暂停、过期、拒绝或恢复；Run 有幂等键、状态机和 fencing token。
- **从单机验证平滑走向生产。** 核心依赖端口抽象；本地用 Fake Runtime/内存组合，持久化契约已在 PostgreSQL、Redis、MinIO 上验证。
- **前后端协议解耦。** Harness 事件是权威事实，AG-UI 只是无状态投影；CopilotKit 控制台可以替换，而不会影响 Agent 执行层。
- **可观测但不绑定厂商。** 应用只发 OpenTelemetry；生产可由 Collector 输出到 Langfuse，本地默认完全关闭 exporter。

这意味着后续开发一个新 Agent，主要工作变成“写 Manifest + prompt/skills/tools + 少量 Python 扩展”，而不是每次重建会话、审批、网关、事件流、存储和 UI。

## 快速开始

```bash
uv sync --group dev
cd web/harness-console && npm install && cd ../..
make dev-up
```

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

Web 首页是 CopilotKit v2 全页对话，而不是原始 Events 面板。`make dev-up` 会幂等发布 `echo-agent@0.1.0`；打开页面后可直接输入普通问题。输入以下内容可以验证完整人工审批与产物流程：

```text
[approval] [artifact] 验证完整流程
```

审批卡片选择“批准并继续”后，同一 Run 自动恢复并显示 `result.txt` 下载卡片。刷新页面会复用本地 thread，并由 CopilotRuntime 的 connect 路由回放已完成消息。原始 AG-UI、消息和状态只在“运行详情”中的 CopilotKit Inspector 查看。

new-api 实际连通性是显式的可选 smoke：

```bash
NEW_API_BASE_URL=https://gateway.example/api \
NEW_API_KEY=... \
NEW_API_MODEL=claude-sonnet-4-6 \
uv run python scripts/smoke_new_api.py
```

未提供三个变量时脚本安全跳过。详细说明见 [docs/local-development.md](docs/local-development.md)。

## 当前边界

Phase 1 是可运行的基础框架与验证面，不是最终控制平面：生产认证、Kubernetes per-run Pod、完整数据库组合根、配额/计费和长期事件订阅仍应在后续阶段实现。
