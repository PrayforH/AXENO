# Archestra 对比后的 Agent Studio 优先级方案

## 1. 结论

Archestra 是面向企业的通用 AI、LLM Gateway 和 MCP 治理平台；Agent Studio
是以 Claude Agent SDK 为执行内核的受控 Agent 构建、运行、评测和发布平台。两者
不应互相替换。Agent Studio 保留 Manifest、不可变 Bundle、Run 状态机、Workspace、
Artifact、审批和发布门禁，只吸收不会削弱可复现性与最小权限原则的能力。

本轮不引入 Archestra 的 Auto 工具模式，也不把 Sandbox 变成可选项。Agent 能看到的
能力继续由已发布 Manifest 明确声明。

## 2. 当前差距

| 领域 | 当前 Agent Studio | Archestra 的启发 | 判断 |
| --- | --- | --- | --- |
| 工作区导航 | 任务、智能体、用量、数据均作为一级入口 | 高频工作与管理能力分层 | 用量暂时隐藏，保留路由和后端账本 |
| 主题 | 5 个页面分别放置切换按钮 | 偏好应属于用户设置 | 只保留“设置 → 外观”一个入口 |
| 工具调用策略 | 调用前按工具、参数、Sandbox 和身份确定性判定 | 工具结果会改变后续上下文的可信度 | 增加 Run 内单调信任状态和结果策略 |
| MCP 凭据 | 服务端引用、短期 Run Lease、完整执行身份 | 用户 OBO、缺失连接时给出可操作提示 | 现有基础可复用，但需要用户连接存储和 OAuth 回调 |
| 工具目录 | Manifest 全量显式传给模型 | `search_tools` / `run_tool` 延迟加载 | 只考虑“已声明工具集内”的延迟加载 |
| 不可信结果 | Prompt 提醒网页内容不可信 | Dual-LLM 隔离原始结果 | 需要独立隔离模型链与评测后再启用 |
| 多入口 | Web 任务页 | Slack、Teams、Email、Webhook | 不是当前产品核心，后置 |

## 3. 优先级与实施计划

### P0：立即执行

#### P0.1 收敛导航和主题

- 从共享工作区导航移除“用量”，保留 `/studio/usage`、API、配额准入和测试。
- 删除任务页、登录页、Agent Studio 侧栏和长期记忆页的主题按钮。
- 在账户设置增加“外观”区，提供浅色和深色两个明确选项。
- 主题仍通过同一个 localStorage key 和根节点 `data-color-mode` 生效。

验收：

- 所有共享侧栏只显示任务、智能体、数据。
- 除设置页外，源代码中没有主题选择控件的挂载点。
- 切换后刷新、跨页面导航和新标签页保持同一主题。
- 浅色、深色构建均不产生混合白色/黑色孤岛。

#### P0.2 上下文感知的确定性工具策略

- 增加 `safe < sensitive < untrusted` 单调信任等级。
- MCP 注册为每个允许工具声明结果信任等级；外部网页检索默认显式标记
  `untrusted`，内部工具默认 `safe`。
- PostToolUse 成功后提升 Run 内信任等级，失败调用不得污染信任状态。
- 后续 PreToolUse 将当前信任等级加入 `PolicyContext`。
- 信任状态不因 Lead 委派给 Sub Agent 而重置。
- 记录不含原始工具结果的 `context.trust.changed` 审计事件。
- 默认策略在不可信上下文中禁止写入长期记忆；Bash 继续要求人工审批。

验收：

- 外部检索成功后，后续长期记忆提议被确定性拒绝。
- 外部检索失败后，信任状态保持不变。
- 工具请求事件包含调用前信任等级，信任变化事件只包含工具名、调用 ID 和等级。
- 现有 Manifest 上限、审批、路径边界和凭据脱敏测试继续通过。

### P1：完成 P0 后实施

#### P1.1 用户级 MCP 连接与 OBO

依赖：

- 加密的用户连接存储；
- OAuth Authorization Code + PKCE 回调；
- refresh token 轮换和撤销；
- MCP Registration 声明 `user_connection` 或 `service_account`；
- Worker 只能获取 Run 绑定的短期 Lease。

验收门槛：

- 凭据解析顺序固定为用户连接、显式团队连接、显式服务账号，禁止隐式借用；
- 缺失连接返回结构化 `connection_required`，界面提供安装/连接入口；
- 用户 A 的 Run 无法解析用户 B 的连接；
- Token 不进入 Manifest、Bundle、事件、Trace 或浏览器。

本轮不实现假的 OBO：当前没有用户连接数据库和上游 OAuth 注册信息，继续使用已有
短期工作负载凭据比把共享密钥包装成“用户凭据”更安全。

#### P1.2 已声明工具集内的按需加载

- Studio 增加 `eager` / `on_demand` 发布选项。
- `on_demand` 只为 Manifest 已声明的工具建立只读目录。
- 模型初始只看到 `search_declared_tools` 和 `run_declared_tool`。
- `run_declared_tool` 再次执行 Manifest、Policy、身份、配额和审批检查。

验收门槛：

- 不能搜索或执行 Manifest 外工具；
- 间接调用与直接调用产生同样的审计、审批和配额事件；
- 小工具集默认保持 `eager`，避免增加无意义的一轮模型调用。

#### P1.3 Dual-LLM 隔离

- 仅对明确标为 `untrusted` 的高风险结果启用。
- 隔离模型只返回受约束结构，不允许调用工具。
- 主 Agent 不接收原始不可信正文。
- 建立注入攻击、信息保真、延迟和成本评测集，通过 Promotion Gate 后才可生产启用。

### P2：按真实需求触发

- Slack、Teams、Email、A2A 多入口；
- 通用知识库和连接器；
- Kubernetes MCP 自助发布；
- Agent 转 Skill。

这些能力会显著扩大身份、数据生命周期和运维边界；没有明确业务入口前不进入当前
Agent Studio 主线。

## 4. 执行顺序

1. 完成 P0.1，并用源码测试证明入口唯一。
2. 完成 P0.2 的领域模型、运行时传播、默认规则和审计事件。
3. 运行 Policy、SDK Gate、Runtime、Web 全量单元测试与生产构建。
4. 使用本地 Docker Compose 验证浅色/深色、共享导航和一次不可信工具调用链。
5. P1 只有在对应依赖和验收测试先落地后才进入实现，禁止跳过安全边界。
