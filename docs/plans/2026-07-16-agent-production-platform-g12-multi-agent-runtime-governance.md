# G12 多智能体运行治理验收记录

## 结论

现有 Claude Agent SDK 的一层 `Lead + Sub` 已从“可配置委派”强化为“运行时受治理委派”。
平台继续让 Lead 作为唯一用户主线，不引入第二套图编排器；Sub 仍由 SDK 的 `Task/Agent`
能力执行，但每次委派都绑定已发布固定版本、角色 alias、独立 Policy 和明确资源上限。

## 已完成范围

- 稳定事件契约统一为 `subagent.started / updated / completed / failed`，并附带
  `harness.subagent.v1`、alias、Agent 名称与版本、Policy、深度、时长及安全 Usage；
- 同一 `AgentVersion` 可通过多个 alias 承担不同职责，事件、Span 和 UI 均按 alias 区分；
- Manifest 增加配置数量、单 Run 子任务数、并发、固定一层深度及 Sub Usage 上限；
- Studio“运行与权限”可配置并持久化上述数量、并发和 Usage 上限，深度 1 与禁用 Sub
  MCP/Python 作为不可放宽的平台边界展示；
- 未声明 alias、配置/解析绑定漂移、超并发、超任务数、超 Usage 和超时均 fail closed；
- 子 Agent 声明嵌套 Sub、MCP 或 Python Tool 会在固定版本解析阶段被拒绝；
- 父 Run 取消不再等待下一条 SDK 事件：Worker 轮询 durable Run 状态，取消正在等待的
  async generator，并为仍活跃的 Sub 写入 `parent_cancelled` 终态；超时同理写入
  `parent_timed_out`；
- SDK 流结束但缺少子任务终态时补写失败，Sub 失败不会被静默吞掉；
- 每个 Sub 终态生成 `harness.subagent.run` Span，只包含 alias、固定版本、Policy、状态、
  时长和聚合 Usage，不包含委派 Prompt、description、summary 或正文；
- Eval 支持 `requiredSubagents`、`forbiddenSubagents`、`minConcurrentSubagents` 和
  `maxConcurrentSubagents`，报告保留实际 alias 与峰值并发；
- AG-UI 执行条继续默认折叠，展开后聚合多个 Sub，显示 alias、版本、时长、工具数和终态。

## 保持不变的边界

- 最大深度固定为 1，不允许 Sub 再委派；
- Sub 不注入 MCP 或 Python Tool；
- 不实现会话 Handoff；
- 并发执行仍由 Claude Agent SDK 负责，Harness 负责身份解析、上限、取消、审计和质量断言，
  不重复实现调度图。

## 验收证据

- 后端验证：537 passed、3 skipped；实时 Langfuse/Tavily 用例按既有策略 opt-in；
- 前端：144 tests passed，Next.js production build passed；
- 失败注入覆盖未绑定 alias、超并发、Usage 超限和缺失终态；
- 取消注入证明等待中的后台 Sub 收到 `CancelledError`，事件顺序为 Sub failed 后 Run cancelled；
- Trace 测试证明同一版本多 alias 可区分，且 Span 不含子任务正文；
- Eval 测试覆盖 required/forbidden alias 与并发峰值的通过和失败路径；
- 浏览器桌面检查确认 Studio 清晰展示 `1 Lead + 3 Sub`、固定版本和并行职责拓扑；
- 390px 窄屏检查确认协同摘要与 Lead/Sub 拓扑无横向错位，关键信息仍可读；
- 前端组件测试确认运行条默认折叠，多个 Sub 在同一执行树中按 alias 聚合。

## 后续约束

资源上限是平台硬边界，不是 Prompt 建议。若以后需要嵌套委派、Sub MCP 或跨会话 Handoff，
必须作为新的显式能力版本设计，不能通过放宽本层校验暗中启用。
