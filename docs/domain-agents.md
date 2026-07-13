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
  - builtin: Task
```

只声明完成任务必需的工具。工具名会原样进入 SDK，权限仍由 Harness 策略控制。

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

`crm-readonly` 是逻辑 ID，不是 URL。服务端通过 `McpServerRegistration` 注入真实 stdio/HTTP/SSE/SDK 配置及显式 allowlist。Manifest 中不要存命令、Header、Token 或环境变量。当前默认组合根使用空 Registry，所以未注册 ID 会 fail closed；部署具体领域 Agent 时必须在服务端组合根完成注册。

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

然后创建绑定固定版本的 Session，再通过 REST Run 或 AG-UI/CopilotKit 发起任务。生产迭代不要修改已发布版本；提升 `metadata.version` 后重新校验、发布，并让新 Session 使用新版本。

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
- 工具参数会进入耐久事件用于审计。领域工具不得把 Token、密码或不必要的个人数据放进参数；字段级 schema 脱敏仍需在生产化阶段补齐。
