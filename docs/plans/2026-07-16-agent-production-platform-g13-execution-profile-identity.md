# G13 Execution Profile、工作负载身份与凭据代理验收记录

## 结论

Agent 构建者现在只声明业务能力并选择平台托管的 Execution Profile，不再接触 Sandbox
Provider 原始参数、模型/MCP 密钥或任意出网地址。发布快照固定 Profile ID、版本和内容哈希；
运行时再按 Run 身份签发短期 Credential Lease，并在结束、取消或失败后统一撤销。

## 已完成范围

- Execution Profile 补齐 Provider、CPU、内存、磁盘、TTL、网络策略、允许的 MCP 引用、
  Provider 配置引用、生产可用标记和版本；
- 默认生产档位绑定 Daytona 与 `registered-mcp-only`，只允许注册过的只读 Tavily MCP；
- Studio 仅显示 Profile 选择器及安全资源摘要，不提供 Endpoint、Token、任意 URL 或 Provider
  参数输入；
- 编译阶段校验 Agent 选择的 MCP 是否在 Profile egress allowlist 内，漂移时 fail closed；
- Preview 固定 Profile ID/版本，Deployment Snapshot 进一步固定 ID、版本和规范化内容哈希；
- 发布接口拒绝 secret-like 和平台托管运行参数；production 拒绝 Local 或未标记生产可用的
  Profile；
- Credential Broker 为模型与 MCP 按租户、Run、资源类型和逻辑引用签发短期租约，支持过期、
  Run 隔离和整 Run 撤销；
- Runtime 只在调用边界注入当前路由所需的模型密钥，Tool Resolver 只注入当前 MCP 所需凭据；
- Worker 在成功、失败、取消和超时的统一清理路径撤销 Run 的全部租约；
- 审计事件只保留 lease ID、Run ID、资源类型、逻辑引用和到期时间，凭据值被模型序列化和
  repr 排除；
- 既有 Daytona live preflight 对目标网络不可达继续返回明确失败，不会静默降级 Local。

## 验收证据

- 后端：543 passed、3 skipped；Ruff、Pyright、包完整性检查和全量 Pytest 均通过；
- 前端：144 tests passed，Next.js production build passed；
- 单元测试覆盖跨 Run 复用拒绝、租约过期、撤销、MCP/模型按需注入与安全审计；
- 发布测试覆盖构建者注入 Provider 参数被拒、Local production 被拒、Profile v1/v2 历史快照
  互不改变；
- 编译测试覆盖未被 Profile egress 允许的 MCP 引用被拒；
- 浏览器桌面与 390px 窄屏复核通过：Runtime 页展示 Profile 版本、Daytona、资源与网络摘要，
  页面无原始凭据字段。

## 保持不变的边界

- Profile 是平台控制面契约，不由 Prompt 或 Agent Bundle 修改；
- 凭据仍由部署环境的 Secret 管理设施提供，数据库和 Artifact 不保存明文；
- 当前生产默认后端为 Daytona；Kubernetes/gVisor 的实际执行适配、Provider 路由和网络策略
  落地属于 G14；
- Profile 内容更新必须升版本，已发布 Deployment Snapshot 不回写。
