# Claude SDK PreToolUse 前置策略与审批桥设计

## 审计结论

1. `RunOrchestrator` 当前在 Runtime 已产出 `tool.request` 后才执行 Policy，不能证明真实 SDK 工具在执行前被拦截。
2. Claude Agent SDK 明确说明完整工具名 `allowed_tools` 会绕过 `can_use_tool`；单独设置 permission callback 不能覆盖所有调用。
3. 现有审批 API 在批准后启动第二个 Worker。若原 SDK query 在等待用户决定，这会造成同一 Run 双执行和 fencing 竞争。

## 方案

为真实 Claude SDK Runtime 注入 `SdkToolGate`，使用匹配所有工具的 `PreToolUse` Hook：

1. Hook 在工具执行前写入耐久 `tool.request`，并用现有 `PolicyEngine` 求值。
2. ALLOW：写入 `tool.allowed`，返回 `permissionDecision=allow`。
3. DENY：写入错误 `tool.result`，返回 `permissionDecision=deny`。
4. ASK：`ApprovalService` 在发出 `approval.requested` 前注册进程内 Future，将 Run 转为 `waiting_approval`；Hook 原地等待。
5. 审批 API 更新持久状态后 resolve Future。批准时原 Hook 返回 allow，原 Worker 继续；拒绝时返回 deny，Run 保持 rejected。

`PreToolUse` 对所有调用生效，即使 SDK settings 或 `allowed_tools` 已放行，因此它是最终安全门。Claude SDK 后续映射出的重复 `tool.request` 由 Runtime 丢弃；工具结果仍正常进入 Harness 事件流。

## 兼容性

- Fake Runtime 不安装 Gate，继续使用现有“Runtime 事件后判断、批准后重新执行 Worker”的确定性测试流程。
- 直接构造且未注入 Gate 的 `ClaudeSdkRuntime` 保持现有测试能力；应用组合根的真实模式必须注入 Gate。
- 当前 waiter 是单 API 进程能力。生产多副本必须替换为 Redis/PostgreSQL 通知或队列 continuation，不能依赖本地 Future。

## 状态与竞态

- `ApprovalService.has_inline_waiter()` 在审批决定前读取；只有没有 waiter 的批准才由 API 安排恢复 Worker。
- waiter 在 `approval.requested` 发布前注册，UI 不可能先点击后注册。
- 决定先持久化 Approval/Run/Event，再唤醒 Hook，保证恢复执行观察到一致状态。
- waiter 在完成或取消后清理。TTL 到期将 Approval 标记 expired、Run 转为 timed_out，并让 Hook deny。
- 重复决定继续由 Approval Repository CAS 拒绝。

## 安全边界

- Hook 事件只保存经过现有事件脱敏边界的工具参数；后续应增加按工具 schema 的字段级脱敏。
- 外部 MCP 仍需 Registry 与 Policy 双重允许。
- 进程崩溃会丢失本地 waiter；Phase 1 将 Run 留在可诊断状态，生产 continuation 需要持久化。

## 验收

- ALLOW/DENY/ASK 三类调用都在工具 handler 之前得到决定。
- ASK 批准只继续原 Worker，拒绝不执行工具。
- SDK options 始终安装匹配所有工具的 PreToolUse Hook。
- SDK 映射不重复落 `tool.request`，但保留 `tool.result`。
- Fake approval 回归、全量 Python/Web 门禁与真实 cc-switch smoke 均通过。

