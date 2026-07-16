# G11 Langfuse Score、Alert 与质量门禁完成报告

## 结论

G11 已在 OTel Trace 与 G09/G10 质量链路之上增加本地耐久 Quality Control Plane。Run 终态首先
落入 Harness 的 Run/Event、规则 Score、Alert Incident 和 Sync Outbox；Langfuse 是异步投影与
分析面，不是运行状态机。Langfuse 不可用时 Agent Run、审批、Artifact 和 Deployment 状态不受
影响，只有 quality sync 进入可恢复重试。

## Trace 关联与属性边界

每个 Run 仍是独立 Trace，同一 Session 通过 `langfuse.session.id` 聚合。Run 根 Trace 现在关联：

- Session ID；
- Agent name/version；
- 可选 Deployment Snapshot/Environment；
- 可选 EvalRun ID。

Telemetry 属性实施 allowlist，只允许 Agent/Run/Session/Deployment/Eval、HTTP、标准 GenAI 用量
和 Harness 低基数运行指标。Prompt、回答、Memory、文件内容和密钥型字段即使误传也只输出
`[REDACTED]`；未知字段和工具参数直接丢弃。

## 规则 Score 与人工反馈

每个终态 Run 生成六个确定性 Score：

- `terminal_success`；
- `tool_reliability`；
- `approval_completion`；
- `duration_budget`；
- `cost_budget`；
- `artifact_integrity`。

Score 固定关联 trace/session/run、AgentVersion、Deployment Snapshot 和 EvalRun。网页/API 可写入
`user_feedback` 人工 Score；自由文本评论不进入 Langfuse 投影，避免把用户回答或审阅敏感信息
带出应用边界。

Langfuse 官方将 Score 定义为可关联 Trace、Observation、Session 或 Dataset Run 的独立质量对象，
并支持 API、人工标注和自动评估来源；本实现使用稳定 score ID 作为幂等键，只发送 ID、名称、
0..1 数值和数据类型。参考：[Langfuse Score 数据模型](https://langfuse.com/docs/evaluation/scores/data-model)、
[Scores via API/SDK](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk)。

## Dataset Adapter 与外部同步

G09 Eval Dataset Version 可投影为 Langfuse Dataset，但只发送 dataset/version、Agent、Case 数量和
content hash，不发送 Case Prompt、期望回答或 Fixture 内容。Dataset 使用官方 v2 create endpoint；
参考：[Langfuse Datasets API v2](https://langfuse.com/changelog/2024-07-02-datasets-api-v2)。

Score/Dataset 先写 `quality_sync_jobs` 和 Redis `harness:quality` lease queue。专用
`harness-quality-worker` 消费任务，失败记录稳定错误码并归还租约，达到最大次数才进入 failed。
Fake Adapter、HTTP MockTransport、PostgreSQL 重建和 Redis 崩溃租约恢复均有测试。

## Alert 与 Promotion Gate

Alert Rule 定义 score name、阈值、最少样本、Dashboard URL 和是否阻断晋级。新 Score 到达后按
AgentVersion 聚合均值并打开/解除 Incident。G10 Promotion 在 Eval Gate 后继续检查本地 Quality
Gate；存在 open blocking Incident 时拒绝创建 Deployment Snapshot。

LLM Judge Score 可以记录和告警，但模型校验明确禁止它单独成为自动 Promotion blocker，也不会
自动触发 rollback。自动回滚必须由后续人工或确定性策略明确授权。

## Secret 隔离与部署

Docker `observability` profile 新增独立 `quality-sync` 服务。只有该服务持有
`HARNESS_LANGFUSE_PUBLIC_KEY/SECRET_KEY`；API、Agent Worker 和 Web 均不持有 Secret Key，模型网关
密钥也不会注入 quality-sync。OTel Collector 继续独立持有其 Basic Auth 并只处理 Trace。

## Studio

“测试与发布”页新增线上质量面板：

- 最新规则/人工 Score；
- 当前版本 Quality Gate；
- open Alert、样本数和是否阻断晋级；
- 可选 Langfuse Dashboard 链接；
- 无运行样本时的真实空态。

## 验收证据

- `make verify`：`525 passed, 3 skipped`，Ruff/Pyright/Agent package 全部通过。
- Web：`143 passed`，Next.js production build 通过。
- Migration 从空库升级到 `0011 (head)`，并验证 `0010 → 0011` 增量升级。
- PostgreSQL 重建后 Score、Rule、Incident、Sync Job 保持一致。
- Redis quality sync worker 租约在 owner 崩溃后恢复。
- Fake Adapter 故障只让 Sync Job 重试，Run 保持 `succeeded`。
- Mock HTTP 验证 Score/Dataset payload 不含 Prompt、回答、Secret 或工具参数。
- InMemory Span Exporter 验证一 Run 一 Trace、Session 聚合、关联属性和 allowlist。
- 浏览器验收确认质量空态、门禁、Alert/Dashboard 布局；390px 宽度正常，控制台无 error/warning。
- 真实 Langfuse Score smoke 为明确 opt-in：`HARNESS_LANGFUSE_LIVE=1`；本轮未向现有项目写测试数据。

三个 skip 分别是 Langfuse live、Tavily live 和真实 Preflight opt-in。
