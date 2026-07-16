# Daytona Sandbox 开发权限设计

## 目标

让所有运行在 Daytona 强隔离 Sandbox 中的用户使用完整的文件开发能力，同时保持 Agent Manifest 的显式能力边界、本地运行的安全审批和可审计的策略决策。

## 设计原则

权限由两个独立层次共同决定：

1. Agent Manifest 声明 Agent 可以看到哪些工具，防止运行时隐式扩权。
2. Harness 策略根据服务端创建的真实 Sandbox 上下文决定工具是否可以执行，防止 Manifest 自行提权。

Sandbox 信任属性只能由 `SandboxProvider` 生成，不能来自网页请求、用户消息、Agent Manifest 或模型输出。

## 方案选择

采用能力感知策略：`SandboxHandle` 显式携带隔离级别，Worker 将它写入不可变的 `RuntimeContext`，SDK PreToolUse Gate 再把它传给 `PolicyEngine`。

不采用以下方案：

- 不根据全局 `HARNESS_SANDBOX_PROVIDER` 静态选择整套策略，因为该方式不能准确表达单次运行实际获得的 Sandbox，也不利于将来按运行选择 Provider 或处理降级。
- 不在 Daytona 中自动注入 Manifest 未声明的工具，因为这会破坏版本快照、最小权限和审计语义。

## 权限模型

隔离级别第一阶段只有两个值：

- `workspace`：本地临时工作目录，不是操作系统安全边界。
- `container`：Daytona 创建的远程容器 Sandbox。

默认工具决策如下：

| 工具 | 本地 `workspace` | Daytona `container` |
| --- | --- | --- |
| `Read` / `Glob` / `Grep` | 自动允许 | 自动允许 |
| `Write` / `Edit` | 需要审批 | 自动允许 |
| `Bash` | 需要审批；包含 `rm ` 的命令拒绝 | 需要审批 |
| 未配置工具 | 拒绝 | 拒绝 |

`Bash` 暂不随 Daytona 自动放行。远程容器隔离了宿主机，但 Claude CLI 仍需要模型网关凭据；在短期凭据、子进程环境隔离或网络出口控制完成前，无审批 Shell 可能读取并外发运行凭据。

该模型对所有进入 Daytona 的用户一致生效，第一阶段不引入用户角色或名单系统。

## 组件与数据流

1. `LocalSandboxProvider` 返回 `isolation_level=workspace`；`DaytonaSandboxProvider` 返回 `isolation_level=container`。
2. `RunOrchestrator` 从实际 `SandboxHandle` 构造 `RuntimeContext`，不从配置字符串推断隔离级别。
3. `SdkToolGate` 从 `RuntimeContext` 构造 `PolicyContext`，加入隔离级别。
4. `PolicyEngine` 继续使用确定性的优先级、特异性和拒绝优先规则；`PolicyRule` 新增可选的隔离级别匹配字段。
5. 每个 `tool.request` 事件记录非敏感的 Sandbox Provider 和隔离级别，审批和拒绝事件继续记录命中的规则原因。

Manifest 仍是能力上限。例如只声明 `Read` 的 Agent 即使运行于 Daytona，也不会看到 `Write`。用于本地验证的 `echo-agent` 将显式加入 `Glob`、`Grep`、`Write`、`Edit` 和 `Bash`，以验证完整策略流。

## 错误与安全处理

- 未知隔离级别在模型校验阶段失败，不允许回退为更宽松权限。
- 未匹配到规则的工具继续 implicit deny。
- 本地 Sandbox 不因目录位于临时路径而被视为强隔离。
- 隔离级别不接受客户端覆盖，也不放入可修改的 Run 输入。
- 工具输入、输出与事件继续执行工作区路径和凭据脱敏。
- Daytona provisioning 或远程传输失败时，运行失败；不得降级到本地后保留容器权限。

## 测试策略

- Sandbox 单元测试证明两个 Provider 生成正确且不可变的隔离级别。
- Policy 单元测试覆盖本地与 Daytona 对 `Read/Glob/Grep/Write/Edit/Bash` 的决策矩阵，以及未知工具拒绝。
- SDK Gate 单元测试证明实际 `RuntimeContext` 决定授权，客户端或工具参数不能伪造隔离级别。
- Worker 集成测试证明 `SandboxHandle` 的可信属性传入 Runtime。
- Manifest/Runtime 集成测试证明只有显式声明的工具会暴露给 SDK。
- AG-UI 测试证明本地写操作出现审批卡片，Daytona 文件写操作不会产生审批请求，Daytona Bash 仍会请求审批。

## 后续演进

只有在具备至少一种可靠控制后，才考虑 Daytona `Bash` 自动放行：每次运行的短期模型凭据、Claude CLI 与工具子进程的环境隔离，或默认关闭外网并使用显式网络 allowlist。用户角色授权属于独立的认证授权阶段，不与本次 Sandbox 能力改造耦合。
