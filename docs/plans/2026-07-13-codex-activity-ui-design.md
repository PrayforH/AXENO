# Codex 风格 Agent 活动界面设计

## 目标

在保留 CopilotKit v2 全页 Chat 的前提下，让用户看懂 Agent 正在做什么，并让开发者可以审计一次 Run 的完整执行过程。重点覆盖工作摘要、工具、子 Agent、JSON、代码、Diff、Artifact、运行指标与错误，不展示原始私有思维链。

## 交互策略

采用双层披露：

- 普通用户：消息内展示一条紧凑执行摘要，可展开关键步骤。
- 开发者：打开“运行详情”后展示完整时间线和事件元数据。

桌面端 Inspector 固定在对话右侧，宽度 360px；窄屏变为底部抽屉。关闭 Inspector 时，Chat 仍占满主区域。

## 架构选择

保留 CopilotKit Chat、输入、流式状态和重连能力，新增 Harness Activity 层：

```text
Claude Agent SDK
  → Harness durable events
  → AG-UI standard tool/message events
  → harness.activity.v1 / harness.subagent.v1 custom events
  → CopilotKit tool/activity renderers
  → compact activity summary + full Run Inspector
```

不自研消息列表；不把 Inspector 降级成原始 JSON 面板。Harness durable event 仍是事实源，因此刷新与 connect 回放必须重建同一时间线。

## 信息安全

“思考”指可审计工作摘要，不是模型隐藏推理：

- 允许：正在分析、准备调用工具、等待子 Agent、整理答案、步骤状态。
- 禁止：原始 chain-of-thought、认证信息、完整环境变量、系统提示、未经脱敏的异常堆栈。
- Developer Inspector 可以显示事件类型、时间、ID、状态和脱敏 payload，但不扩大敏感数据范围。

## 事件模型

### `harness.activity.v1`

统一表示 Run 与执行阶段：

```json
{
  "id": "event-id",
  "kind": "run|analysis|tool|subagent|result|artifact|error",
  "status": "queued|running|waiting|succeeded|failed|cancelled",
  "title": "正在分析代码库",
  "summary": "已读取 3 个文件",
  "timestamp": "2026-07-13T00:00:00Z",
  "duration_ms": 1234,
  "sequence": 8,
  "metadata": {}
}
```

`metadata` 仅包含白名单字段：model、provider、tool name、turns、cost、stop reason、artifact coordinates 等。

### `harness.subagent.v1`

```json
{
  "id": "parent-tool-use-id",
  "parent_id": "parent-tool-use-id",
  "name": "architecture-reviewer",
  "task": "检查边界与风险",
  "status": "running|succeeded|failed",
  "summary": "发现 2 个边界问题",
  "timestamp": "..."
}
```

子 Agent 的 partial stream 只更新子 Agent 活动，不再映射为主 Assistant 的 `message.delta`。

### 标准 Tool 事件

继续使用 `TOOL_CALL_START / ARGS / END / RESULT`，以便 CopilotKit 管理工具生命周期。Harness 提供统一 wildcard renderer；`Task`/`Agent` 工具升级为子 Agent renderer；审批与 Artifact 保留专用 renderer。

## 组件

- `ActivitySummary`：主消息中的折叠摘要，显示当前状态、工具数、子 Agent 数、耗时。
- `ExecutionSpine`：按 sequence 排列的执行脊柱，节点类型包括分析、工具、子 Agent、结果、错误。
- `RunInspector`：右侧/底部完整时间线，含模型、耗时、轮次、费用和 stop reason。
- `ToolActivityCard`：统一工具卡，显示名称、状态、参数摘要、结果摘要。
- `SubagentActivityCard`：委派目标、父子关系、状态、输出摘要。
- `StructuredValue`：JSON 树、原文切换、复制、深度和长度限制。
- `CodeBlock`：语言标签、行号、复制、横向滚动。
- `DiffBlock`：新增/删除/上下文行样式，长内容折叠。
- `ErrorActivity`：就地错误和恢复建议。

## 视觉系统

主题来自 Agent 执行台，而不是通用 SaaS 卡片：

- Graphite `#101512`：主文本与深色 Inspector。
- Paper `#F4F6F2`：页面底色。
- Porcelain `#FFFFFF`：对话面。
- Moss `#2A6B53`：运行中和成功节点。
- Amber `#C97B20`：等待、审批与警告。
- Code Slate `#111A17`：代码、JSON 与 Diff 背景。

字体继续使用 Avenir Next（正文）、Avenir Next Condensed（标题）、SF Mono（数据）。唯一强调元素是贯穿每个 Run 的“执行脊柱”；其余卡片取消重阴影，使用层级、间距和细线表达结构。

动效集中在一个位置：运行中的脊柱节点使用低频呼吸动画；完成后静止。尊重 `prefers-reduced-motion`。

## 内容渲染

- JSON：默认展示前两层；数组/对象可展开；字符串、数字、布尔、null 使用不同但克制的语义色；完整原文可切换。
- 代码：从字段名、Markdown fence 或内容启发识别语言；未知语言按纯文本显示。
- Diff：识别 unified diff；`+`、`-`、`@@` 分别呈现，不执行 HTML。
- 日志：保留换行，默认最多 20 行，展开后最多 500 行，超限显示截断提示。
- 二进制和无法识别内容：显示媒体类型、大小和下载入口。

## 错误与降级

- 无效 JSON 回退到安全纯文本，不让 renderer 崩溃。
- 活动缺少结束事件时显示“流中断”，Inspector 保留已收到步骤。
- 未知工具走 wildcard renderer。
- 未知 custom event 只进入 Inspector，不污染主对话。
- 连接失败、Run 失败、取消分别使用独立终态文案。

## 验收

1. 普通文本回答保持现有 CopilotKit 流式体验。
2. 工具调用展示紧凑卡片；参数与结果可以展开为美化 JSON/代码/Diff。
3. `Task`/`Agent` 调用展示为子 Agent，partial text 不进入主回答。
4. Run Inspector 能从 durable replay 重建完整时间线。
5. 模型、provider、耗时、轮次、费用、stop reason 可见。
6. 审批与 Artifact 既出现在对话中，也出现在执行脊柱中。
7. 桌面与移动布局可用，键盘焦点清晰，reduced motion 生效。
8. 浏览器无运行错误；页面刷新、普通问题、工具问题、子 Agent 问题均完成真实模型验收。
9. 事件与 UI 不包含 token、系统提示或原始思维链。
