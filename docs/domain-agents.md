# 快速构建领域 Agent

Harness 把 Agent 开发分成两层：平台层统一提供模型网关、Session/Run、Workspace、Artifact、事件、审批和 OpenTelemetry；领域层只定义业务角色、知识、工具、协作方式和验收标准。新领域不需要复制一套执行框架。

## 1. 创建骨架

```bash
uv run harness agent init invoice-reviewer
uv run harness agent validate agents/invoice-reviewer/agent.yaml
```

生成目录：

```text
agents/invoice-reviewer/
├── agent.yaml
├── prompts/
│   └── system.md
└── README.md
```

先修改 `prompts/system.md` 的四个部分：Mission、Operating workflow、Boundaries 和 Output contract。一个有效的领域 Agent 应明确它负责的业务结果、证据从哪里来、哪些动作需要批准、失败时如何停止，以及最终结果的结构和质量门槛。

## 2. 选择工具边界

### SDK builtin

适合文件、Shell 和 Agent 委派等 Claude Agent SDK 原生能力：

```yaml
tools:
  - builtin: Read
  - builtin: Glob
  - builtin: Grep
  - builtin: Write
  - builtin: Edit
  - builtin: Bash
```

只声明完成任务必需的工具。工具名会原样进入 SDK，Manifest 是 Agent 能力上限；Harness 不会因为运行在 Daytona 就注入未声明工具。执行权限再由服务端可信的 Sandbox 隔离级别控制：本地 `Write/Edit/Bash` 进入审批，Daytona `Write/Edit` 自动允许，Daytona `Bash` 仍审批。这样领域包不能通过修改 Manifest 自行声明“已隔离”来提权。

### Python 领域工具

适合低延迟的内部查询、计算和已有 Python SDK 封装。Manifest 只保存 import 引用：

```yaml
tools:
  - python: billing_agent.tools:lookup_invoice
```

对应模块必须作为 Harness 运行环境中的已安装包存在，并导出一个 `SdkMcpTool` 或由它们组成的非空序列：

```python
from typing import Any

from claude_agent_sdk import SdkMcpTool


async def lookup(arguments: dict[str, Any]) -> dict[str, Any]:
    invoice_id = str(arguments["invoice_id"])
    record = await invoice_repository.get(invoice_id)
    return {"content": [{"type": "text", "text": record.model_dump_json()}]}


lookup_invoice = SdkMcpTool(
    name="lookup_invoice",
    description="Read one invoice by its exact ID",
    input_schema={
        "type": "object",
        "properties": {"invoice_id": {"type": "string"}},
        "required": ["invoice_id"],
    },
    handler=lookup,
)
```

Harness 将这些工具组合为进程内 `harness-python` MCP Server。重复名称、非法导出或无法导入都会在 SDK 请求开始前失败。

### 外部 MCP

适合需要独立部署、独立凭据、跨语言或高隔离级别的系统：

```yaml
tools:
  - mcp: crm-readonly
```

`crm-readonly` 是逻辑 ID，不是 URL。服务端通过 `McpServerRegistration` 注入真实 stdio/HTTP/SSE/SDK 配置及显式 allowlist。Manifest 中不要存命令、Header、Token 或环境变量。默认组合根已经注册 `tavily-readonly`；其他未注册 ID 会 fail closed，部署具体领域能力时必须在服务端组合根完成注册。

### 复用通用检索与协作能力

领域 Agent 可以直接组合 Harness 已审核的通用能力，不需要复制主 Agent、审批组件或事件协议。例如，一个需要外部事实检索、同时需要把本地材料交给只读助手分析的 Agent 可以声明：

```yaml
tools:
  - builtin: Read
  - builtin: Task
  - mcp: tavily-readonly
subagents:
  - ref: helper-agent@1.0.0
```

`mcp: tavily-readonly` 只暴露 Tavily 的 search 与 extract，真实 URL、Header 和凭据由服务端 Registry 注入。Claude Agent SDK 会把远端的连字符工具名规范化为 `mcp__tavily__tavily_search` 和 `mcp__tavily__tavily_extract`，Registry allowlist 与 Policy 必须使用规范化后的名字。网页结果必须作为不可信数据处理，回答中应列出来源标题和完整 URL。`helper-agent@1.0.0` 只有 `Read/Glob/Grep`，适合归纳工作区证据，不能写文件、执行 Shell 或访问外部服务。

新增工具时应保持四层边界一致：Manifest 声明能力上限，服务端 Registry 注入连接，Policy 明确 `allow / deny / ask`，自动化测试覆盖允许和拒绝路径。领域项目复用 Harness 的共享审批与运行界面，因此审批、执行进度、子任务树和终态处理会自动出现，不应为每个领域 Agent fork 一套 Web UI。

## 3. 复用模型网关与平台能力

Manifest 的 model 只表达 route、模型和能力需求：

```yaml
model:
  route: new-api-default
  model: claude-sonnet-4-6
  requiredCapabilities:
    - streaming
    - tool_use
```

endpoint 和 credential 由 Harness 启动配置提供。本地 `make dev-up-cc-switch` 复用 cc-switch 当前 Anthropic-compatible Provider；Agent 包不感知 new-api Token。Session、Run、工作区归档、产物、AG-UI 和 Langfuse/OTel 链路也无需领域代码重复实现。

## 4. 校验、发布与运行

每次修改版本内容后先校验：

```bash
uv run harness agent validate agents/invoice-reviewer/agent.yaml
```

校验会读取提示词和 skills、执行完整 schema/路径/secret 检查，并输出确定性内容哈希。Phase 1 的发布 API 接受 API 进程可见的本地路径：

```bash
curl -sS http://127.0.0.1:8000/v1/agents \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-ID: local' \
  -H 'X-User-ID: developer' \
  -d '{"path":"agents/invoice-reviewer/agent.yaml"}'
```

然后创建绑定固定版本的 Session，再通过 REST Run 或 AG-UI/assistant-ui 发起任务。生产迭代不要修改已发布版本；提升 `metadata.version` 后重新校验、发布，并让新 Session 使用新版本。

## 5. 用评测而不是聊天感觉验收

每个领域至少维护三类样例：

- Happy path：输入完整，能正确调用工具并产出约定结构。
- Ambiguous path：输入不足，Agent 会澄清而不是猜测。
- Safety path：越权写入、敏感信息或高风险动作会拒绝或请求审批。

建议记录任务成功率、字段正确率、工具选择、审批命中、耗时、Token/成本和人工修订量。当前 Harness 已提供 Run/Event/OTel 基础；数据集 runner 与版本回归门禁是后续控制面能力。

## 当前安全边界

- 主 Agent 支持 builtin、Python 和已注册 MCP；subagent 暂只支持 builtin，声明自定义工具会显式失败。
- MCP Registry 与 allowlist 属于服务端部署配置，Manifest 无权自行提升权限。
- 真实 SDK 模式已使用 catch-all `PreToolUse` Hook，在执行前完成 allow/deny/ask。Phase 1 的 inline 审批 waiter 只适用于单 API 进程；生产多副本需要用 Redis/PostgreSQL 通知或队列 continuation 替换本地 Future。
- Sandbox Provider 生成不可伪造的 `workspace/container` 隔离事实。Daytona 保护宿主机，但模型网关凭据仍存在于 Claude CLI 运行环境，因此 `Bash` 在短期凭据或网络出口隔离完成前不会自动放行。
- 工具参数会进入耐久事件用于审计。领域工具不得把 Token、密码或不必要的个人数据放进参数；字段级 schema 脱敏仍需在生产化阶段补齐。
