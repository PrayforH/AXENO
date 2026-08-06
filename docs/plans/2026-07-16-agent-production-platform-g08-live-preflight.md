# G08 真实 Sandbox / Model / MCP Preflight 完成报告

## 结论

G08 已将 Preview 从“静态配置可编译”升级为“目标执行环境可运行”的部署前证明。
每次 Preview 都绑定精确的 Draft revision、content hash 和 package hash，并依次验证
Sandbox、模型流式 Tool Use、MCP、审批策略、Workspace 文件操作和制品收集。任一阶段失败、
超时或取消都会形成版本化结果并回收资源，不会静默回退到 Local Sandbox，也不会创建正式
AgentVersion。

## 稳定结果协议

- Schema：`harness.preflight/v1`。
- 终态：`passed`、`failed`、`cancelled`、`timed_out`。
- 阶段：`bundle`、`sandbox_provision`、`sandbox_prepare`、`model`、`mcp`、
  `approval`、`workspace_artifact`、`cleanup`。
- 每个阶段记录开始/完成 Event、耗时、状态和稳定错误码；原始异常、Prompt、Credential
  不进入 API、日志或 Trace。
- 结果嵌入 Preview 的版本化 JSON payload，因此本 Goal 不新增数据库 migration；API 另提供
  Preview Event 查询接口。

## 真实检查路径

### Sandbox

新增统一的安全命令执行契约，Local 与 Daytona Provider 均支持 argv、环境变量、超时和取消。
敏感配置通过进程环境注入，不拼接到命令行。Preflight 完整执行
`provision -> prepare -> execute/collect -> destroy`；Controller 在长任务期间续租，取消或超时
会中断在途命令并在 `finally` 中清理资源。

生产 Worker 只使用配置选中的真实 Sandbox。目标 Provider 失败时 Preview 失败关闭，不回退
Local；Local 只保留给显式选择的本地开发和 Fake 测试组合。

### Model

在目标 Sandbox 内向 Anthropic-compatible Messages 端点发起流式请求，强制调用
`preflight_echo`，同时校验 SSE 完整结束与 `tool_use`。不兼容模型、缺失 Tool Use 能力、鉴权
和目标网络错误均返回稳定公开错误码。

### MCP

检查分为两层：先从目标 Sandbox 验证端点可达和鉴权状态，再由 Worker 使用 MCP 客户端完成
`initialize`、`tools/list` 与注册表中经过审核的只读 smoke。工具名称不匹配、401/403、404、
服务不可用、网络不可达和非法响应均有稳定错误码。当前 Tavily 注册为只读搜索 smoke。

### 审批、Workspace 与 Artifact

Preflight 使用实际 PolicyEngine 验证 Write、Edit、Bash；声明 Bash 的 Agent 必须命中 ASK，
写能力不得被策略拒绝。随后在隔离 Workspace 中读取输入、写入并编辑输出、执行 Bash，最后
收集 `preflight.txt` 并校验文件名、大小和 SHA-256。Preview 生命周期短，因而这里保存的是
不可变制品证明而不是长期 Run Artifact 下载对象。

## 可靠性与安全性

- Fake Probe 覆盖所有阶段失败、Draft 漂移、审批不匹配、取消、超时和清理。
- Controller 使用租约心跳和 fencing CAS，Worker 崩溃或并发取消后仍可收敛到单一终态。
- 取消每 250ms 检查一次并主动取消在途动作；超时会标记具体阶段后执行 cleanup。
- OpenTelemetry Span 仅允许 Preview ID 与阶段名；单元测试验证属性白名单。
- 变更文件敏感信息扫描通过，未发现 Anthropic、Langfuse、Daytona 或 Tavily Secret。
- Daytona/MCP/模型端到端测试为显式 opt-in；本次环境未提供完整真实配置，因此正确跳过，
  没有伪造外部通过证据。

## Studio 体验

Preview 创建后自动轮询 queued、provisioning、cancelling 状态。完成后以紧凑详情展示八个阶段、
通过/跳过数量、稳定错误和制品摘要。浏览器验证确认 Ready 状态、展开详情、全部阶段和制品摘要
可读，控制台无错误或警告。

## 验收证据

- `make verify`：Ruff、Pyright、3 个 Agent package 检查通过；`499 passed, 2 skipped`。
- G08 关键定向测试：`27 passed`。
- Web：`141 passed`，Next.js production build 通过。
- PostgreSQL、Redis、Preview 生产组合测试通过。
- 浏览器人工检查通过。
- `git diff --check` 与 Secret 扫描通过。

两个 skip 分别是既有 Tavily live 集成测试和本 Goal 新增的真实 Preflight opt-in 测试；它们只在
提供有效外部配置时运行。
