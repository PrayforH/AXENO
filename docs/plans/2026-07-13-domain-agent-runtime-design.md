# Domain Agent Tool Runtime 与开发脚手架设计

## 目标

让业务开发者可以在 Harness 的稳定运行时之上，用一份 Agent Manifest、领域提示词和少量工具代码快速构建具体领域 Agent，同时保持模型网关、会话、工作区、事件、审批与可观测能力由 Harness 统一托管。

本阶段交付两个最小闭环：

1. Manifest 已声明的 `builtin`、`python`、`mcp` 工具都能被 Claude Agent SDK Runtime 确定性解析。
2. `harness agent init/validate` 能生成并校验领域 Agent 骨架，减少复制示例和手工排错。

## 方案选择

采用统一 `ToolResolver`，而不是在 Runtime 中直接导入任意函数或要求所有本地工具独立部署：

- Builtin 工具保持 Claude Agent SDK 原生名称，不改变已有 Agent。
- Python 引用采用 `module:attribute`；attribute 必须是一个 `SdkMcpTool` 或它们的有限序列，并被包装为进程内 SDK MCP Server。
- MCP 引用是 Harness 服务端 Registry 的逻辑 ID。Manifest 不携带命令、URL、Header 或密钥。
- Registry 显式声明允许自动放行的完整工具名；Manifest 本身不能提升权限。

这样既保留本地领域开发的低摩擦，也为外部 MCP 的隔离部署和集中运维留出边界。

## 运行时模型

`ToolResolver.resolve(manifest)` 生成不可变的 `ResolvedTools`：

- `builtin_tools`：传给 `ClaudeAgentOptions.tools`。
- `mcp_servers`：传给 `ClaudeAgentOptions.mcp_servers`。
- `allowed_tools`：仅包含服务端注册时显式批准的工具名。

解析规则：

1. Builtin 工具保持声明顺序并去重。
2. 所有 Python 引用先导入并验证，再组合为单个 `harness-python` SDK MCP Server；工具名必须全局唯一。
3. 外部 MCP Registry 按逻辑 ID 查找；未知 ID、重复 server 名、非法配置或冲突工具名均 fail closed。
4. 输出顺序稳定，便于快照、测试和追踪。
5. 错误只包含逻辑引用，不输出 Registry 内的环境变量、Header 或密钥。

Subagent 本阶段继续只支持 builtin 工具。若 subagent 声明 Python/MCP 工具，Runtime 显式拒绝，而不是静默忽略；后续在 SDK 支持的权限语义确认后再扩展。

## 权限与安全边界

`ClaudeAgentOptions.allowed_tools` 可能绕过 `can_use_tool`，因此本阶段不会根据 Manifest 自动放行自定义工具。只有 Harness 端 `McpServerRegistration.allowed_tools` 明确列出的完整名称才进入 SDK allowlist。

当前 Orchestrator 是在 SDK 映射出 `tool.request` 后执行策略判断；这不能证明真实 SDK 工具在执行前被拦截。本阶段仅完成工具解析和暴露，不宣称已经提供生产级事务审批。完成后审计将优先设计 SDK `can_use_tool`/`PreToolUse` 与 Harness ApprovalService 的前置桥接。

## 开发者体验

新增无网络依赖的 CLI：

```text
harness agent init invoice-reviewer
harness agent validate agents/invoice-reviewer/agent.yaml
```

`init` 创建：

- `agent.yaml`：固定版本、模型 route、builtin 工具和保守权限默认值。
- `prompts/system.md`：角色、边界、工作流和输出契约模板。
- `README.md`：本地验证、发布及 Python/MCP 扩展说明。

初始化拒绝覆盖已有目录。`validate` 使用生产发布同一套 Manifest 解析器和路径规则，并输出规范化的 Agent 标识与内容哈希。

## 错误处理

- Python 引用格式错误、模块不存在、attribute 不存在或类型不正确：启动 Run 前失败。
- MCP 逻辑 ID 未注册：启动 Run 前失败。
- CLI 名称非法、目标已存在或 Manifest 无效：非零退出码和可操作错误，不打印 traceback。
- 所有异常避免包含 credential、环境变量值和 MCP Header。

## 验收标准

- 测试证明 builtin、Python SDK MCP、外部 MCP Registry 能正确组装进 `ClaudeAgentOptions`。
- 未注册引用、重复名称、非法 Python 导出以及 subagent 自定义工具均 fail closed。
- 现有 echo Agent 和 cc-switch/new-api 真实模型链路不回归。
- CLI 能初始化一个新领域 Agent，并由同一 CLI 校验通过；重复初始化安全失败。
- Ruff、Pyright、Python 测试、Web 测试和 Web build 全部通过。

