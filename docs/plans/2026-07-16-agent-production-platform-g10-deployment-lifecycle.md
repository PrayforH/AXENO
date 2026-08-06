# G10 环境部署生命周期完成报告

## 结论

G10 已把“发布 Agent Version”与“让环境开始承载该版本”拆成两个独立事实。Agent Version、
Deployment Snapshot 均不可变；Environment 只是带 revision 的可变路由指针。发布、灰度和回滚
通过耐久 Deployment reconcile 完成，失败时不修改最后健康环境。新 Session 按环境路由解析一次
并固定 Agent Version/Snapshot，已存在 Session 不会被后续切流改变。

## 数据模型与持久化

Migration `0010` 新增三张租户隔离表：

- `deployment_environments`：`test/canary/production` 环境、revision、加权 Snapshot 路由和最后
  健康 Snapshot；
- `deployment_snapshots`：Agent/Version、manifest/package hash、执行制品 digest、Execution
  Profile、非敏感配置、Eval Gate 与可选 Preview 证明；
- `deployments`：promote/rollback 操作、目标与上一 Snapshot、灰度比例、期望环境 revision、
  幂等键、状态、fencing token 和脱敏错误码。

PostgreSQL Repository 对 payload envelope 做一致性校验，并对 Environment revision 与 Deployment
status/fencing token 使用 CAS。Redis 使用独立 `harness:deployment` namespace、去重与 visibility
lease；非终态 reconcile 归还同一租约，终态才 ACK，因此 Controller 崩溃后可重新获取任务。

## 发布与回滚语义

Promotion 必须满足：

1. 目标是已有的不可变 published Agent Version，且包含 package hash；
2. G09 required Eval Dataset 门禁通过；
3. 若提交 Preview 证明，则 Preview 必须 ready、未 stale 且 package hash 完全一致；
4. 请求携带当前 Environment revision；
5. Snapshot 配置禁止 secret/token/password/credential/API key 等密钥型字段。

服务先写不可变 Snapshot 和 Deployment，再由 Controller 执行部署 hook。只有 hook 成功且
Environment CAS 成功，才更新路由。并发发布使用相同 revision 时仅一方能切流；另一方进入
`failed/environment_revision_conflict`。部署 hook 失败时只记录稳定错误码，最后健康 Snapshot、
revision 和路由均保持不变。

全量发布把环境切成单 Snapshot 100%；灰度保留健康 Snapshot，仅把指定比例的新 Session 路由到
目标 Snapshot。Rollback 只能选择同一 Agent、同一环境、已通过 Eval Gate 的历史 Snapshot，仍然
通过新 Deployment 和 CAS 执行，而不是修改或覆盖历史对象。

## Session 版本固定

创建 Session 现在必须二选一：

- 直接指定 `agent_version`，保持原有 API 行为；
- 指定 `environment=test|canary|production`，平台用 Session ID 做稳定哈希，解析环境加权路由。

解析结果把 `agent_version`、`environment`、`deployment_snapshot_id` 一起持久化。后续发布、灰度、
回滚只影响尚未创建的新 Session；旧 Session、SDK resume 和工作区恢复继续使用原版本。这避免同一
会话在多轮对话中发生 Prompt、Skills、Tools 或 Sub Agent 契约漂移。

## API、Worker 与 Studio

新增 Studio API：

- Agent 环境列表、Deployment 列表、Snapshot 列表；
- Deployment 明细；
- promote；
- 指定环境和历史 Snapshot rollback。

`studio:deploy` 仅授予 owner/admin。生产 Worker 把 Deployment Controller 作为独立 maintenance
loop，与 Preview、Eval 和普通 Run 执行互不阻塞。本地 `auto_execute` 模式提供有界 drain，API
集成测试可验证最终状态而不会停在 queued。

Studio “测试与发布”页新增真实部署控制面：

- test/canary/production 当前 revision、版本与权重；
- 发布当前不可变版本，canary 已有健康版本时默认仅灰度 10% 新会话；
- queued/reconciling 状态轮询；
- 部署历史、上一版本到目标版本与 package hash 差异；
- 失败错误码；
- 从历史已验证 Snapshot 回滚。

界面明确提示“新 Session 解析当前路由、旧 Session 固定原快照”，避免用户把环境切流误解为修改
正在运行的对话。

## 验收证据

- `make verify`：Ruff、Pyright、3 个 Agent package 检查通过；`518 passed, 2 skipped`。
- Web：`143 passed`，Next.js production build 通过。
- Migration 从空库完整升级至 `0010 (head)`，三张 deployment 表存在。
- PostgreSQL Engine/Repository 重建后 Environment、Snapshot、Deployment、幂等键和 fencing
  状态保持一致。
- Redis Deployment Controller 租约在 owner 崩溃后可重新获取。
- 测试覆盖幂等发布、密钥型配置拒绝、旧 Session 固定、新 Session 灰度、历史回滚、部署失败保留
  健康环境、并发 CAS 仅一方成功、API 发布与环境 Session 固定。
- 浏览器验收确认三环境卡片、发布状态、版本差异入口和空态可读；390px 下三张卡片同宽单列，
  控制台无 warning/error。
- `git diff --check` 与全部变更/新增文件 Secret 扫描通过。

两个 skip 是需要外部配置的 Tavily live 与真实 Preflight opt-in 测试，与 G10 的本地确定性覆盖
无关。
