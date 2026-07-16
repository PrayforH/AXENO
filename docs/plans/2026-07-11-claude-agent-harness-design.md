# Claude Agent Harness 设计

日期：2026-07-11  
状态：已确认  
目标版本：v0.1（一期）

## 1. 背景与目标

Claude Agent SDK 提供了 Claude Code Agent 循环、内置工具、子智能体、Skills、MCP、Hooks、Sandbox 和 Session Resume，但不直接提供多租户服务、Agent 版本治理、分布式任务、审批恢复、工作区归档、统一 API、WebUI 或生产级可观测性。

本项目在 Claude Agent SDK 之上建设一套独立 Harness，使后续 Agent 主要通过 Manifest、Prompt、Skills、Tools 和业务测试完成开发，同时共享生产运行能力。

### 1.1 核心目标

- Python Core 与 FastAPI 服务层同时可用。
- new-api Anthropic-compatible 模型为默认入口，官方 Claude 为兼容基准和回退。
- 支持 Kubernetes 多副本部署和每 Run 独立 Sandbox。
- PostgreSQL 保存持久业务状态，Redis 承担队列、事件、锁和取消信号，MinIO/S3 保存附件、工作区快照与产物。
- Agent 使用 Manifest + Python 扩展点定义，并形成不可变版本。
- 异步 Run 为核心，提供 SSE/AG-UI 实时事件、取消、中途追加消息和人工审批。
- OpenTelemetry 为可观测标准，提供 Langfuse OTLP 配置模板；本地一期默认关闭导出。
- 独立 Harness API 是事实源，AG-UI 是 UI 协议适配器，CopilotKit 是一期验证 WebUI。
- 所有基础设施通过端口/适配器隔离，为未来增加其他 Agent Runtime 保留空间。

### 1.2 非目标

一期不建设以下能力：

- Agent Marketplace。
- 在线 Prompt/Skill 编辑器。
- 计费结算系统。
- 可视化工作流编排器。
- 多区域调度。
- OpenAI Responses 或 LangGraph API 完整兼容。
- 完整管理后台。
- Langfuse 本地部署。
- 除 Claude Agent SDK 外的第二个运行时实现。

## 2. 总体架构

采用控制面与执行面分离的模块化架构。

```text
                         Harness Control Plane
┌──────────────────────────────────────────────────────────────────┐
│ FastAPI Gateway                                                  │
│ Agent Registry │ Session/Run Service │ Approval │ Artifact       │
│ Policy Engine  │ Auth/Tenant         │ Event Query              │
└──────────────────────────────┬───────────────────────────────────┘
                               │ PostgreSQL + Redis Streams
                               ▼
                          Harness Data Plane
┌──────────────────────────────────────────────────────────────────┐
│ Worker / Run Orchestrator                                        │
│ SandboxProvider → Local / Kubernetes Job                         │
│ AgentRuntime → Claude Agent SDK                                  │
│ Tool/MCP Registry │ Hook Pipeline │ Workspace Manager            │
└──────────────────────────────┬───────────────────────────────────┘
                               │
             ┌─────────────────┼──────────────────┐
             ▼                 ▼                  ▼
        PostgreSQL           Redis             MinIO/S3
        元数据/Transcript     队列/事件/锁        附件/工作区/产物

       Harness Events → AG-UI Adapter → CopilotKit WebUI
       Harness Spans  → OTel Collector → Langfuse（生产可选）
```

### 2.1 仓库结构

```text
claude-agent-harness/
├── packages/
│   ├── harness-core/
│   ├── harness-sdk-runtime/
│   ├── harness-api/
│   ├── harness-worker/
│   ├── harness-storage/
│   ├── harness-sandbox/
│   ├── harness-observability/
│   └── harness-agui/
├── web/harness-console/
├── agents/
├── deploy/
│   ├── docker-compose/
│   ├── helm/
│   └── otel-collector/
└── tests/
    ├── contract/
    ├── integration/
    └── e2e/
```

一期可在一个 Python distribution 中实现上述包边界，避免过早拆分发布流程；边界仍需通过依赖方向强制执行。

### 2.2 依赖规则

- `harness-core` 不依赖 FastAPI、Redis、Kubernetes、Langfuse 或 Claude Agent SDK。
- API、Worker 和 Runtime 只依赖 Core 定义的领域对象与端口。
- 基础设施包实现 Core 端口，不允许领域层反向 import 基础设施。
- WebUI 只访问 Harness API 和 AG-UI Adapter。
- Claude Agent SDK 只能出现在 `harness-sdk-runtime`。

## 3. Agent 定义与发布

### 3.1 Manifest

```yaml
apiVersion: harness/v1alpha1
kind: Agent
metadata:
  name: research-agent
  version: 1.2.0
  labels:
    domain: research
spec:
  runtime: claude-agent-sdk
  model:
    route: new-api-default
    model: claude-sonnet-4-6
    fallbackRoute: anthropic-official
    fallbackModel: claude-sonnet-4-6
    requiredCapabilities: [streaming, tool_use]
  prompt:
    system: prompts/system.md
  skills:
    - skills/web-research
  tools:
    - builtin: Read
    - python: app.tools.search:web_search
    - mcp: internal-data
  subagents:
    - ref: fact-checker@1.0.0
  hooks:
    - python: app.hooks.audit:audit_tool_call
  permissions:
    policy: standard-research
  workspace:
    mode: isolated
    restoreSession: true
    archiveOnComplete: true
  limits:
    maxTurns: 30
    timeoutSeconds: 1800
    maxBudgetUsd: 10
```

### 3.2 发布规则

- 生命周期：`draft -> validated -> published -> deprecated -> archived`。
- 只有 `published` 版本可以创建生产 Session。
- 已发布版本不可变；修改产生新版本。
- Manifest、Prompt、Skill、Python 包、策略和 MCP 配置均生成内容哈希。
- 生产 Session 必须绑定具体版本；`latest` 只允许开发环境使用。
- 密钥不得进入 Manifest 或快照，只保存 Secret 引用。
- Python 扩展通过预注册 entry point 加载，不允许任意 import 字符串执行未审计代码。

### 3.3 核心领域对象

- `AgentSpec`：解析后的 Agent 配置。
- `AgentVersion`：不可变发布快照。
- `Session`：连续对话与工作区的逻辑容器。
- `Run`：一次异步 Agent 执行。
- `Message`：用户、Agent、工具或系统消息。
- `RunEvent`：运行过程中的有序事实。
- `ToolSpec` / `ToolCall`：工具声明和调用记录。
- `ApprovalRequest`：待审批动作。
- `Artifact`：附件、报告、图片、数据文件或工作区快照。
- `Workspace`：Sandbox 中可恢复、可归档的文件集合。
- `ModelRoute`：模型网关、映射、能力和回退策略。
- `PolicyDecision`：`allow`、`deny` 或 `ask`。

## 4. 模型网关与兼容策略

### 4.1 路由优先级

1. 默认使用 new-api Anthropic-compatible endpoint。
2. 运行前检查模型能力缓存。
3. 若网关不可用、协议不兼容或缺失必要能力，按 Agent 策略切换官方 Claude。
4. 回退必须产生显式事件和 Trace 属性，不得静默发生。

### 4.2 能力画像

每个 `ModelRoute` 维护：

- Anthropic SSE 是否正确。
- `tool_use` / `tool_result` 是否完整。
- 是否支持并行工具调用。
- thinking block 是否兼容。
- 是否保留 token usage。
- 最大上下文与输出限制。
- 是否支持所需 beta header。
- 子智能体运行稳定性。

兼容等级：

- `full`：通过全部必需和增强能力测试。
- `degraded`：满足 Agent 必需能力，但部分增强能力不可用。
- `unsupported`：缺失 Agent 必需能力。

一期提供显式配置画像和冒烟探测；不实现复杂动态基准测试平台。

## 5. Session、Run 与消息模型

### 5.1 Session

Session 绑定：

- tenant/user。
- AgentVersion。
- Claude SDK session ID。
- 当前工作区快照。
- 消息与 transcript。
- 默认 model route。
- 创建、归档和过期策略。

Session 可以产生多个顺序或分支 Run。并发写入同一 Session 时通过 Redis 分布式锁保证单写者；只读事件查询不加互斥锁。

### 5.2 Run 状态机

```text
queued
  └─> provisioning
        └─> running
              ├─> waiting_approval ──> running
              ├─> cancelling ────────> cancelled
              ├─> failed
              └─> succeeded
```

附加终态：`timed_out`、`rejected`。

规则：

- 状态转换使用数据库条件更新，保证幂等。
- Worker 必须持有 Run lease；lease 过期后可被其他 Worker 接管。
- 每个 Run 有幂等键，客户端重试创建请求不会重复执行。
- Run 超时、预算超限和取消均是结构化终态。
- 中途追加消息通过控制通道发送给活动中的 `ClaudeSDKClient`；无法即时注入时排队到下一个 turn。

### 5.3 事件模型

所有 RunEvent 具有：

- `event_id`：全局唯一。
- `run_id`、`session_id`、`tenant_id`。
- `sequence`：Run 内严格递增。
- `type`、`timestamp`。
- `payload`、`schema_version`。
- `trace_id`、可选 `span_id`。

一期事件类型：

- Run：queued、started、status、completed、failed、cancelled。
- Message：start、delta、completed。
- Tool：requested、started、result、failed。
- Subagent：started、progress、completed、failed。
- Approval：requested、approved、rejected、expired。
- Artifact：created、ready、failed。
- Model：selected、fallback、usage。
- Workspace：restored、archived。

PostgreSQL 保存权威事件，Redis Streams 用于实时分发。消费者使用 `event_id + sequence` 去重。

## 6. 工具、MCP 与审批

### 6.1 Tool Registry

支持三类工具：

- Claude Code 内置工具。
- Python SDK MCP 工具。
- 外部 MCP Server 工具。

Python 工具被包装为 SDK in-process MCP Server。工具 schema 在 Agent 发布时校验并快照；运行时仅加载 AgentVersion 声明的工具。

### 6.2 Policy Engine

每次敏感工具调用统一产生策略请求，输入包括：

- tenant、user、AgentVersion。
- tool 名称和类型。
- 参数摘要和敏感标签。
- 文件路径、命令、网络域名或 MCP Server。
- Sandbox 等级和数据分类。

输出：

- `allow`：立即执行。
- `deny`：拒绝并向 Agent 返回结构化原因。
- `ask`：创建 ApprovalRequest，Run 进入 `waiting_approval`。

审批具有过期时间、审批人范围、一次性 token 和不可变审计记录。批准后 Worker 恢复 Session；拒绝后将拒绝结果作为工具结果交回 Agent。审批 API 必须幂等。

一期策略实现基于声明式规则和 Python 扩展点；不引入独立策略语言或 OPA，保留未来适配端口。

## 7. Sandbox 与工作区

### 7.1 SandboxProvider

接口能力：

- `provision(run)`。
- `restore(workspace_snapshot)`。
- `execute(runtime_command)`。
- `signal(cancel/interrupt)`。
- `archive()`。
- `destroy()`。

实现：

- `LocalSandboxProvider`：一期开发与集成测试，使用隔离临时目录和子进程。
- `KubernetesSandboxProvider`：生产默认，每 Run 独立 Job/Pod。

### 7.2 工作区生命周期

```text
Session snapshot / input artifacts
            ↓
       restore to sandbox
            ↓
       Claude SDK execution
            ↓
      incremental artifacts
            ↓
       archive workspace
            ↓
        destroy sandbox
```

- Pod 文件系统不作为持久化来源。
- MinIO/S3 保存输入附件、输出 Artifact 和可选工作区归档。
- PostgreSQL 只保存对象元数据、哈希和 URI，不保存大文件。
- Artifact 先写临时 key，校验完成后原子发布为 ready。
- 默认禁止跨租户对象访问，下载使用短期签名 URL。

## 8. 存储与一致性

### 8.1 PostgreSQL

核心表：

- tenants、users。
- agents、agent_versions。
- sessions、runs、messages。
- run_events。
- tool_calls、approval_requests。
- artifacts、workspace_snapshots。
- model_routes、model_capabilities。
- audit_logs。
- transcript_entries。

Claude SDK `SessionStore` 实现写入 transcript_entries，并支持 resume 所需的 load/list/subkeys/delete。

### 8.2 Redis

- Run queue：Redis Streams consumer group。
- Run event fan-out：Streams/PubSub；持久补偿读取 PostgreSQL。
- Session lock 和 Run lease：带 fencing token 的分布式锁。
- Cancel/interrupt 控制信号。
- 短期能力缓存和限流计数。

Redis 不是权威持久层，丢失后可以从 PostgreSQL 恢复任务和事件。

### 8.3 MinIO/S3

- 原始附件。
- Artifact。
- 工作区快照。
- 大型工具结果。
- 可选的调试包。

所有对象使用 tenant/session/run 前缀和内容哈希，服务端加密由部署环境配置。

## 9. API 设计

API 前缀：`/v1`。

### 9.1 Agent

- `POST /agents/validate`
- `POST /agents`
- `POST /agents/{name}/versions`
- `POST /agents/{name}/versions/{version}/publish`
- `GET /agents`
- `GET /agents/{name}/versions/{version}`

### 9.2 Session 与 Run

- `POST /sessions`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `POST /sessions/{session_id}/runs`
- `GET /runs/{run_id}`
- `POST /runs/{run_id}/messages`
- `POST /runs/{run_id}/cancel`
- `GET /runs/{run_id}/events`
- `GET /runs/{run_id}/events/stream`（SSE）

### 9.3 Approval 与 Artifact

- `GET /approvals`
- `POST /approvals/{approval_id}/approve`
- `POST /approvals/{approval_id}/reject`
- `POST /artifacts/uploads`
- `GET /artifacts/{artifact_id}`
- `GET /artifacts/{artifact_id}/download`

API 使用 cursor pagination、结构化错误、幂等键和 tenant-scoped authorization。SSE 支持 `Last-Event-ID` 恢复。

## 10. AG-UI 与 CopilotKit

Harness API 保持事实源，`harness-agui` 将领域事件转换为 AG-UI 事件：

- Run 生命周期映射到 AG-UI Run 事件。
- Message delta 映射到文本消息流。
- ToolCall 映射到工具调用与结果事件。
- Approval 映射到 HITL/interrupt 交互。
- Session 状态映射到 state snapshot/delta。
- Subagent、Artifact、成本和 Trace 链接通过受版本控制的 custom event/state 扩展表达。

一期 CopilotKit Console 包含：

- Agent/版本选择。
- Session 列表和新建会话。
- 流式消息。
- 工具调用卡片。
- 审批卡片。
- Run 状态、取消和追加消息。
- Artifact 列表与下载。
- 简化的子智能体时间线。
- token、费用、延迟摘要。
- Langfuse Trace 链接占位；本地关闭时隐藏。

WebUI 不直接持久化事实状态，刷新后从 Harness API 恢复。

## 11. 可观测性

### 11.1 标准

- OpenTelemetry 是 Core 唯一观测抽象。
- W3C trace context 跨 FastAPI、Redis Worker 和 Claude SDK 子进程传播。
- 生产推荐应用发送到集群内 OTel Collector，再转发 Langfuse OTLP HTTP endpoint。
- 本地一期 `OTEL_ENABLED=false`，使用 no-op provider；测试可使用 in-memory exporter。

### 11.2 Span 层级

```text
agent.run
├── session.load
├── sandbox.provision
├── workspace.restore
├── model.request
├── subagent.run
├── tool.call / mcp.call
├── approval.wait
├── artifact.upload
├── workspace.archive
└── session.persist
```

统一属性包括 tenant、user、agent/version、session、run、model route、model、tool、token、费用、延迟、重试和错误类型。

敏感数据默认不导出：完整 prompt、SQL 结果、工具大结果、附件内容和密钥。仅记录哈希、大小、行数、分类和 Artifact ID。生产环境提供采样和脱敏钩子。

## 12. 安全与多租户

- 所有领域查询强制 tenant scope。
- Secret 仅通过环境/Kubernetes Secret/Vault 注入。
- 默认最小工具权限；Bash、Write、外网和敏感 MCP 进入策略判断。
- 每 Run 独立生产 Sandbox，使用非 root 用户、只读基础镜像、资源限额和 NetworkPolicy。
- Artifact 使用短期签名 URL。
- Manifest 扩展点必须来自受信任包清单。
- 审批、策略、模型回退和管理员操作写入不可变审计日志。
- API 支持 OIDC/JWT；一期本地提供显式 dev identity，不允许静默匿名生产模式。
- 日志和事件在写入前执行密钥与敏感字段清洗。

## 13. 错误处理与可靠性

### 13.1 错误分类

- `validation_error`：Manifest、schema 或输入错误，不重试。
- `policy_denied`：策略拒绝，不重试。
- `model_protocol_error`：网关协议不兼容，可回退。
- `model_transient_error`：限流、5xx、网络错误，指数退避。
- `tool_error`：作为结构化工具结果返回 Agent，是否重试由策略决定。
- `sandbox_error`：创建/恢复失败，可由 Worker 重试。
- `storage_error`：保持 Run lease，有限重试后失败。
- `cancelled` / `timed_out` / `budget_exceeded`：明确终态。

### 13.2 可靠性规则

- API 创建操作使用 idempotency key。
- Worker 使用 at-least-once 消费；所有副作用必须幂等。
- Run lease 使用 fencing token 防止僵尸 Worker 写入。
- 事件先写 PostgreSQL，再发布 Redis；发布失败由 outbox 重放。
- Artifact 使用临时对象和最终状态，避免半成品可见。
- Sandbox 清理由后台回收器兜底。
- 不自动重试具有外部副作用且无法证明幂等的工具。

## 14. 测试与评测

### 14.1 测试层级

- 单元测试：领域状态机、Manifest、策略、事件转换、路由和脱敏。
- 端口契约测试：SessionStore、Repository、EventBus、ArtifactStore、SandboxProvider。
- 集成测试：PostgreSQL、Redis、MinIO、FastAPI、Worker。
- Runtime 测试：使用 fake Claude SDK transport 验证消息、工具、审批、取消和 resume。
- 网关冒烟：对配置的 new-api 运行普通流式、工具调用、并行工具、thinking 和子智能体测试。
- E2E：CopilotKit/AG-UI -> API -> Queue -> Worker -> Runtime -> Event -> UI。
- 故障测试：Worker 崩溃、lease 过期、Redis 重启、重复消息、MinIO 超时。

### 14.2 一期验收场景

1. 发布示例 Agent。
2. 创建 Session 和异步 Run。
3. SSE/AG-UI 收到有序流式消息。
4. Python 工具正常调用并展示结果。
5. 敏感工具触发审批，批准后 Run 恢复。
6. Run 可取消。
7. Artifact 上传、归档和下载正常。
8. Worker 重启后 Run 可恢复或明确失败。
9. Claude SDK transcript 可持久化并 resume。
10. CopilotKit 可以完成上述交互。
11. 本地无 Langfuse 时系统无错误、无阻塞。

## 15. 一期开发范围

一期按纵向切片交付：

### Phase 1A：可运行骨架

- Core 领域对象与端口。
- Manifest 解析和校验。
- 内存存储、内存事件总线、LocalSandbox。
- FakeRuntime。
- FastAPI Agent/Session/Run/SSE API。
- 最小 Worker。

### Phase 1B：本地生产依赖

- PostgreSQL Repository 与 SDK SessionStore。
- Redis queue/event/lock。
- MinIO ArtifactStore。
- Docker Compose。
- Outbox 和 Worker lease。

### Phase 1C：Claude SDK 与交互

- ClaudeAgentSdkRuntime。
- new-api route 配置与官方 Claude fallback 配置。
- Python SDK MCP Tools 和外部 MCP。
- Policy/Approval。
- Workspace restore/archive。

### Phase 1D：验证 UI

- AG-UI Adapter。
- CopilotKit Console。
- 端到端场景和本地运行文档。

## 16. 风险与控制

- **SDK/CLI 快速变化**：Runtime Adapter 隔离，锁定版本，建立升级契约测试。
- **new-api 仅协议兼容**：能力画像、冒烟测试和官方 Claude 回退。
- **过度平台化**：一期严格限制在纵向闭环，不建设 Marketplace、计费和工作流设计器。
- **Kubernetes Sandbox 冷启动**：开发使用 LocalSandbox；生产后续评估预热池。
- **多状态源不一致**：PostgreSQL 为权威状态，Redis 可重建，MinIO 以元数据状态机发布。
- **敏感数据外泄**：最小权限、脱敏、短期 URL、租户隔离和默认关闭完整内容观测。
- **Agent 行为难以回归**：版本快照、固定评测集、网关能力测试和成功任务成本指标。

## 17. 成功指标

- 新 Agent 从模板到可运行的时间。
- Agent 业务代码之外的重复基础设施代码比例。
- Run 成功率、恢复率和取消响应时间。
- 工具调用成功率和审批闭环成功率。
- 事件与 Trace 完整率。
- 单次成功任务的 token、费用与 P95 延迟。
- SDK 升级需要修改的 Agent 数量。
- 新 Agent 接入验证 WebUI 的工作量。
- 生产故障平均定位时间。

## 18. 最终决策摘要

- 采用模块化 Harness，而不是 SDK 薄封装或一期完整平台。
- Python Core + FastAPI 服务适配层。
- new-api Anthropic-compatible 优先，官方 Claude 回退。
- PostgreSQL + Redis + MinIO/S3。
- Kubernetes 多副本，生产每 Run 独立 Pod；本地 LocalSandbox。
- Manifest + Python 扩展点，不可变 AgentVersion。
- 独立 Harness API，异步 Run + SSE。
- 策略引擎风险分级与人工审批恢复。
- OpenTelemetry-first，Langfuse 为生产可选目标；本地一期关闭。
- AG-UI Adapter + CopilotKit 验证 WebUI。
