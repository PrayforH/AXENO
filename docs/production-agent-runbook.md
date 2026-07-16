# Production Agent release runbook

平台级构建、签名、`test → canary → production` 同制品晋级见
[Release and environment promotion](runbooks/release-promotion.md)；失败恢复和灾备见
[Rollback and disaster recovery](runbooks/rollback-disaster-recovery.md)；上线总检查见
[Final production readiness](runbooks/final-production-readiness.md)。本文继续描述单个领域 Agent
内容发布与运行质量检查。

## Release gate

在发布一个新的 `name@version` 前确认：

- 业务 owner、风险 owner、值班联系人明确。
- 系统提示词包含 Mission、workflow、evidence、safety、output contract。
- Skill 是本次发布所需的最小 SOP，目录内没有 secret 或环境配置。
- Tools 使用最小权限；写操作幂等并有归属校验、超时和结构化错误。
- Policy Profile 与工具能力一致；只读 Agent 不声明 Write/Edit/Bash。
- Subagent 固定版本，Task 的输入和返回契约可独立验收。
- `maxTurns`、`timeoutSeconds`、`maxBudgetUsd` 有有限值。
- happy/ambiguous/safety 和关键业务回归已通过。
- Daytona/Sandbox、模型网关、MCP 注册和凭据在目标环境可用。
- Daytona workspace 同步/归档字节与成员上限符合业务输出规模。
- Redis processing lease、heartbeat、过期回收与业务写工具幂等性已验证。
- API 服务 Bearer 已随机生成、通过 secret store 注入且未进入浏览器或仓库。
- Langfuse/OTel 不记录 prompt、文件内容、Token 或密码。

执行：

```bash
make verify
make smoke-daytona
uv run harness agent eval agents/<name>/agent.yaml \
  --base-url "$HARNESS_BASE_URL/v1" \
  --tenant release-validation \
  --user release-bot \
  --publish \
  --junit work/evals/<name>.xml
uv run harness agent pack agents/<name>/agent.yaml --output dist/agents
```

`smoke-daytona` 必须从 Daytona sandbox 内访问到模型网关；Docker 宿主机本身能访问不算通过。私网 new-api 应使用同网段或已打通 VPN/VPC 路由的自托管 Daytona，不能退回无隔离的 local provider 作为生产替代。

CLI 调用受保护的生产 API 时应由部署环境注入 `HARNESS_API_BEARER_TOKEN`；不要把
服务 token 写进 Eval fixture、Manifest 或命令历史。

## Rollout

1. 以 `application/zip` 上传不超过 25 MiB 的 bundle，保留 bundle SHA256、Manifest runtime hash、package hash 和 CI 报告。
2. 新建测试 Session，验证模型 route、工具列表、审批和产物下载。
3. 只让新 Session 使用新版本；不要改变已经运行的 Session 绑定。
4. 小流量观察成功率、拒绝率、审批等待、P95 时长、预算和错误类型。
5. 指标稳定后逐步扩大；旧版本继续保留以便回滚。

## Langfuse / OTel 核对

一次 Harness Run 是一个分布式 Trace；同一对话的多个 Run 通过
`langfuse.session.id` 归入同一个 Session。至少核对以下 span：

- `harness.worker.run`
- `harness.sandbox.provision/prepare/collect/destroy`
- `harness.agent.assets.stage`
- `harness.mcp.resolve`
- `harness.model.run`
- `harness.artifact.publish`（仅在启用本地 SDK publisher 或远端 HTTP publisher 时）
- `harness.artifact.publish_outputs`（Daytona `outputs/` 自动发布时）

模型 span 带 Agent 名称/版本、运行时内容哈希、完整 package hash、模型 route、
Provider、实际模型、Policy Profile、Skill/Tool 数量、轮次、SDK/API 耗时、成本，
以及白名单化的 input/output/cache Token 计数。这些是低敏维度；原始 prompt、
模型输出、上传文件、memory、任意 Provider 原始 usage 字典和 credential 必须保持脱敏。

`timeoutSeconds` 覆盖一次完整 SDK 执行，包括模型、工具与人工审批等待。命中后 SDK
查询会被取消，Run 进入 `timed_out`，错误码为 `runtime_timeout`。需要长时间审批的业务
应提高这个明确上限，而不是取消超时。

Claude Agent SDK 返回 `ResultMessage(is_error=True)` 时，Harness 会先保留经过脱敏的
`runtime.result`（用于定位用量、HTTP 状态和 SDK 错误子类型），再将 Run 置为
`failed/runtime_result_error`。供应商错误或预算耗尽不会误记为成功，也不会与 Harness
自身的墙钟超时混为一类；供应商返回的原始错误文本不会写入事件或 trace。

## Rollback

发布版本不可原地修改或覆盖。回滚时：

1. 停止为新版本创建 Session。
2. 将入口配置恢复为上一个已验证版本。
3. 允许安全的在途 Run 完成；有外部副作用风险的 Run 按业务预案取消或人工接管。
4. 用 Run ID、Trace ID、Agent content hash 和 bundle hash 保留证据。
5. 修复后提升版本重新发布，不复用失败版本号。

## Incident triage

优先区分：模型网关兼容性、MCP/凭据、Policy 拒绝、审批等待、Sandbox、业务工具、
预算/超时、输出回归。`timed_out` 与预算耗尽、人工取消是三种不同终态，不要混为模型
错误。不要通过临时扩大工具权限来“验证是否能跑”；应使用固定输入在
隔离租户复现，并对比上一 Agent 版本的 live eval 和 Trace。
