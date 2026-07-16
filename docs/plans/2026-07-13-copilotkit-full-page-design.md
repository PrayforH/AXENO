# CopilotKit 全页交互台设计

日期：2026-07-13  
状态：已授权按推荐方案实施

## 1. 目标

将一期以原始 AG-UI Events 为中心的协议验证台，替换为面向用户的全页 CopilotKit Chat。通用聊天交互全部复用 CopilotKit；Harness 只承担标准 AG-UI 后端、身份边界和审批、产物、子智能体等领域扩展。

成功标准：

- 用户默认看到连续对话，而不是 JSON Events。
- 支持新建/恢复会话、流式回答、取消、刷新恢复。
- 工具调用呈现为可读的执行状态。
- 高风险工具以内联卡片批准或拒绝，批准后 Run 自动恢复。
- Artifact 在对话中展示名称、类型、大小，并可鉴权下载。
- 原始事件、Run ID、路由与 Trace 只在开发者抽屉中出现。
- 本地 Fake Runtime 可完整验证，不需要模型密钥或 Langfuse。

## 2. 方案选择

### 2.1 采用：CopilotKit v2 全页 CopilotChat

使用 CopilotKit 官方 Chat、Agent hook 和 Human-in-the-loop/Tool renderer。优点是消息、输入、流式状态、自动滚动、重连和可访问性由社区组件维护；Harness 只做协议和领域组件。

### 2.2 不采用：基于 AG-UI Client 自研 Chat

虽然灵活，但会重复建设消息列表、输入、流式合并、线程恢复、可访问性与移动端适配。

### 2.3 不采用：Open WebUI/LibreChat 适配

它们擅长模型聊天，但 Harness 的 Run、审批、Artifact、子智能体和 AG-UI 需要较重的非标准桥接。

## 3. 总体架构

```text
CopilotChat full page
        │
        ▼
Next.js /api/copilotkit
CopilotRuntime + proxied AG-UI Agent
        │  注入 tenant/user、转发取消和恢复游标
        ▼
Harness POST /v1/agui
RunAgentInput -> Session/Run -> live SSE Events
        │
        ├─ Harness API/Worker（事实源）
        ├─ Approval API
        └─ Artifact API
```

浏览器不直接持有 Harness 内部身份头。Next.js BFF 从本地配置或未来登录态解析身份并注入所有请求，避免 EventSource/header 限制，并保留未来生产认证入口。

现有 `GET /v1/agui/runs/{id}/events` 作为调试与回放接口保留。新增的标准 `POST /v1/agui` 接收 AG-UI `RunAgentInput`，创建或恢复 Harness Session，创建 Run，并在同一个响应中持续输出 SSE。

## 4. 页面结构

全页只有一个主要任务：与当前 Agent 对话。

- 顶栏：Agent/版本、当前 Session、新建会话、开发者模式。
- 主区：CopilotChat 官方消息与输入组件。
- 消息内：普通 Tool 状态、Approval、Artifact、Subagent Activity。
- 开发者抽屉：原始 AG-UI、Run 状态、事件序号、模型路由、Trace ID；默认关闭。

不建设运行列表、Agent 编辑器或运营仪表盘，避免把验证台扩张为管理后台。

## 5. 领域组件

### 5.1 工具调用

普通 `TOOL_CALL_*` 使用 CopilotKit 默认 Tool UI。参数默认摘要展示，展开后才显示完整 JSON；工具失败显示可读错误，不暴露堆栈或密钥。

### 5.2 人工审批

Harness `approval.requested` 映射成专用 HITL tool/interrupt，前端注册 `HarnessApprovalRenderer`：

- 显示工具、目标资源、风险等级、理由和过期时间。
- 批准/拒绝按钮具有 pending 状态，防止重复提交。
- 决策调用 Approval API；批准后由 Worker 自动恢复。
- 决策结果回写 AG-UI tool result，卡片转为只读终态。

### 5.3 Artifact

`artifact.ready` 映射为 `HarnessArtifactRenderer`，展示名称、媒体类型、大小和哈希摘要。下载由 BFF 代理并注入身份，禁止无身份的直接对象 URL。文本与图片可在后续增加预览，一期只要求安全下载。

### 5.4 子智能体

使用 AG-UI Activity/Custom Event 显示折叠的“研究中/校验中/已完成”。默认不展示子智能体原始消息，避免主对话噪声。

## 6. 数据流

### 6.1 新消息

1. CopilotChat 构造 `RunAgentInput`，包含 thread ID、messages、state。
2. BFF 转发到 Harness 标准 AG-UI endpoint，并注入身份。
3. Harness 查找或创建 Session，使用客户端 run/thread 标识建立稳定映射。
4. Harness 创建幂等 Run，并启动 Worker。
5. Worker 事件实时投影为 AG-UI SSE；CopilotChat 合并成消息和工具状态。
6. Run 终态后事件仍由 PostgreSQL/内存事件仓库可回放。

### 6.2 刷新恢复

线程 ID 保存在 URL/local storage。重新连接时 BFF 传递最后事件游标；Harness 先回放缺失事件，再切换到实时流。UI 状态必须可从 Harness 事实源重建，不依赖浏览器内存。

### 6.3 审批恢复

Run 进入 `waiting_approval` 后 SSE 保持可重连。前端提交决策，Approval Service 幂等更新状态；批准触发 Worker resume，后续事件继续进入同一 thread。

## 7. 错误处理

- BFF 无身份：返回 401，不连接 Harness。
- Agent/版本不存在：在 Chat 内显示可恢复错误，并保留用户输入。
- SSE 中断：指数退避重连并携带最后事件 ID。
- 重复消息或决策：依赖 idempotency key 和 Approval CAS 返回已有结果。
- Run 失败：显示用户可读错误码和“重试为新 Run”；详细错误仅在开发者抽屉。
- Artifact 不存在或跨租户：404，不泄露对象元数据。
- CopilotKit runtime 不可用：页面提供连接状态，不回退到自研事件渲染。

## 8. 兼容与迁移

- 迁移到 CopilotKit 当前 v2 API，锁定明确版本。
- 后端继续使用官方 `ag-ui-protocol` 类型，增加标准请求 schema 与流式 route。
- 保留现有 Harness API 和调试 Events route，避免破坏已完成测试。
- 现有自研首页替换为 CopilotChat；复用的只有 Agent selector、Approval/Artifact 领域逻辑和开发者抽屉。

## 9. 测试与验收

- Python mapper/route 单测：RunAgentInput、文本、Tool、Approval、Artifact、终态、重连。
- API 集成：标准 POST SSE、身份、幂等、取消、审批恢复、Last-Event-ID。
- Web 单测：CopilotChat provider、领域 renderer、错误状态。
- 浏览器 E2E：发消息 -> 流式回答；触发审批 -> 批准 -> 自动恢复；Artifact 出现并下载；刷新后恢复会话。
- 回归：现有 Python 全套、真实 PostgreSQL/Redis/MinIO、Fake Runtime E2E、Next production build 全部通过。
- 本地启动：`make dev-up` 后访问 `http://127.0.0.1:3000` 可完成上述流程，且 `HARNESS_OTEL_ENABLED=false`、无需 Langfuse。

