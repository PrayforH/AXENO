# Agent Studio 用户体系与任务/智能体隔离设计

## 1. 目标与结论

Agent Studio 已具备账号注册、密码/OAuth 登录、JWT、刷新令牌、租户成员与角色管理，也已经在 AG-UI 线程、附件、审批和运行详情入口做了部分用户归属校验。但当前核心资源边界并不一致：任务以 `tenant_id + user_id` 隔离，智能体草稿和已发布版本仍主要按 `tenant_id` 隔离；预览、评测、部署、质量数据等智能体派生资源也多为租户级查询。多个用户加入同一工作区后，会出现草稿、智能体目录或派生资源互相可见以及名称冲突。

本次采用 WeKnora 的“认证主体 + 工作区成员 + 资源所有者”三层模型，并保持 Agent Studio 现有租户/RBAC 结构：

- `tenant_id` 是工作区边界，任何请求都不能跨工作区。
- `user_id` 是私有资源所有者，任务和智能体默认仅本人可读写。
- `role` 只决定管理能力，工作区 Owner/Admin 默认不能读取其他用户的任务正文、附件、草稿、密钥和智能体内容。
- 内部 Worker 不模拟终端用户，而是沿任务固化的所有者身份访问智能体和派生资源。
- 本期不开放用户主动共享。后续共享必须增加显式 ACL，不能把“同租户”重新解释为“所有人可见”。

## 2. WeKnora 参考结论

WeKnora 的认证中间件先解析用户、目标工作区和成员角色，再把 tenant、user、role 和 principal 同时写入请求上下文。其会话服务在读写时同时约束 tenant 与 user；跨用户访问统一伪装为资源不存在。管理员仅对 API Key、IM、嵌入式渠道等明确的工作区托管会话拥有额外只读入口，不能修改其他用户的私人会话。

可复用的原则不是照搬表结构，而是：身份必须在中间件一次解析；Repository 查询必须带完整作用域；普通管理员不能绕过内容隐私；后台任务必须携带可验证的终端主体；历史无所有者数据必须显式迁移，不能长期使用空 owner 作为共享后门。

## 3. 当前状态与差距

| 领域 | 当前状态 | 风险 | 本次目标 |
|---|---|---|---|
| 用户认证 | 注册、登录、OAuth、刷新令牌、禁用账号已具备 | 登录固定依赖默认租户；身份更多用于 UI 和 RBAC | 保持现有登录流程，明确用户为资源授权主体 |
| 成员与角色 | Owner/Admin/Member/Viewer 已具备 | 管理角色容易被误用于内容越权 | 角色管理与私人内容访问分离 |
| AG-UI 线程 | Binding 已按 tenant/user 复合键存储 | 少量内部查询仍只带 tenant | 所有入口统一通过 owner 校验 |
| Session/Run | Session 已含 user_id，Run 可由 Session 反查所有者 | 子资源若只按 run_id 查询可能旁路 | Run、Event、Approval、Artifact、Workspace 全部继承 Session owner |
| 智能体草稿 | payload 有 createdBy，但 Repository 只按 tenant/draft 查询和列表 | 同工作区用户可见、可改他人草稿 | Repository 与服务强制 tenant/user/draft |
| 已发布智能体 | 仅 tenant/name/version 主键，没有 owner | 同名冲突、目录互见、运行解析歧义 | 主键和查询加入 owner_user_id |
| 子智能体 | ref 仅 name@version | 可能解析到他人同名版本 | 在根智能体 owner 作用域内解析所有依赖 |
| 预览/评测/部署/质量 | 多数记录有 requestedBy/createdBy，但列表与读取按 tenant | 派生信息泄露或可被取消/回滚 | 继承智能体 owner；用户入口按 owner 过滤 |
| MCP 凭据/记忆/输入文件 | 已有 user 作用域或请求校验 | 需防止智能体解析时错用他人资源 | 运行始终使用 Session owner |

## 4. 目标数据模型

所有私人资源使用统一的 `ResourceScope(tenant_id, owner_user_id)`。API 中的 `user_id` 永远来自已验证 JWT/服务凭据，禁止从请求体或可伪造 Header 覆盖。

### 4.1 智能体

`agent_drafts` 新增 `owner_user_id NOT NULL`，主键调整为 `(tenant_id, owner_user_id, draft_id)`，并增加 `(tenant_id, owner_user_id, updated_at)` 与 `(tenant_id, owner_user_id, name)` 索引。`createdBy`/`updatedBy` 继续保留审计语义，但不再作为查询权限的替代品。

`agent_versions` 新增 `owner_user_id NOT NULL`，主键调整为 `(tenant_id, owner_user_id, name, version)`。同一工作区不同用户可以发布相同的 `name@version`，但一个用户自己的版本仍保持不可变和幂等。

`Session` 增加或固化 `agent_owner_user_id`。正常交互任务中它等于 `session.user_id`；将来显式共享智能体时可以不同，但必须由 ACL 解析后写入，Worker 只相信 Session 快照。

### 4.2 任务及子资源

Session 继续以 `user_id` 作为任务 owner。Run 不重复维护 owner，避免双写不一致；所有用户态 Run 查询先读取 Run，再读取 Session，并校验 `session.user_id == identity.user_id`。Event、Approval、Artifact、InputArtifact、ThreadFile 和 WorkspaceSnapshot 必须通过拥有者 Run/Session 校验，不允许直接以 tenant + id 返回。

后台队列仅携带 tenant/run_id，Worker 读取 Session 后得到 `user_id` 与 `agent_owner_user_id`，再解析智能体、MCP 凭据、知识绑定和记忆。这样异步执行不会因为没有浏览器 JWT 而退化为租户级访问。

### 4.3 派生资源

Preview 使用 `requested_by` 作为 owner；EvalDataset 使用 `created_by`，EvalRun 使用 `requested_by`；DeploymentSnapshot 使用 `created_by`，Deployment 使用 `requested_by`；Trigger 使用 `created_by`。API 的 get/list/cancel/update/promote/rollback 均要求 actor 与 owner 一致。环境路由属于私人智能体命名空间，键加入 owner，避免同名智能体相互覆盖。

质量分数和告警通过 Run/Agent owner 过滤。平台维护、过期回收和 Worker Controller 可以使用内部 Repository 方法跨 owner 扫描，但这些方法不暴露给用户 API。

Studio 管理的 MCP 凭据使用 `(tenant_id, owner_user_id, reference)` 作为复合主键。相同工作区的用户可以分别配置同名 MCP，页面只显示当前用户的配置状态；运行时按 Session 固化的 `agent_owner_user_id` 取凭据。旧租户级密文迁移给其最后配置者，并保留旧 AAD 的只读解密兼容，下一次保存时自动按用户级 AAD 重加密。

## 5. 授权规则

用户态访问按以下固定顺序执行：

1. 验证 Access Token，解析 tenant、user、roles。
2. 验证用户账号未禁用且当前 tenant membership 仍有效。
3. 根据资源 id 查询 tenant 内记录；不存在则返回 404。
4. 校验 owner_user_id，或沿 Run → Session、Artifact → Run → Session 解析 owner。
5. owner 不匹配时同样返回 404，避免泄露资源是否存在。
6. 最后检查动作权限，例如 `tasks:write`、`agents:publish`。

Owner/Admin 只拥有成员、配额、工作区策略等控制面权限，不自动获得私人内容访问权。平台 Worker、迁移和维护进程使用独立的内部方法，不通过伪造 user_id 绕过校验。

## 6. API 与前端变化

现有 URL 保持兼容，不在 URL 中暴露 owner。列表接口只返回当前用户资源；详情、下载、取消、归档、发布和部署对跨用户 id 返回 404。创建草稿或发布版本时 owner 从 identity 注入。

账号菜单继续展示当前用户与工作区角色。智能体列表和任务侧栏增加“仅显示我的资源”的明确提示；空状态不再暗示工作区无任何资源。管理员成员页增加说明：成员管理权限不包含查看成员任务和智能体内容。所有 401/403/404 错误保持统一，不把 owner id 返回给前端。

## 7. 迁移策略

迁移分为结构迁移、归属回填和约束收紧三步，确保 174 可回滚：

1. 新增 nullable owner 列和新索引，服务暂不切流。
2. 草稿 owner 从 payload.createdBy 回填；已发布版本优先通过匹配草稿的 name、publishedVersion 和 publishedHash 归属。仍无法归属的版本，在某 tenant 仅有一个 Owner 时归给该 Owner；其他记录写入迁移报告并阻止发布切换。
3. 预览、评测、部署、触发器使用已有 requestedBy/createdBy 回填 owner；任务继续使用 sessions.user_id。
4. 校验每张表 owner 为空数量为零、同 owner 唯一键无冲突后，改为 NOT NULL 并切换复合主键/唯一约束。
5. 先部署兼容读版本，再执行迁移，再部署强制隔离版本。174 数据库和 compose 配置都在切换前备份。

旧数据不会因为空 owner 对所有用户可见；无法确定归属时宁可隐藏并生成运维清单，也不恢复租户级共享。

## 8. 测试门禁

### 8.1 用户体系

- 注册、登录、刷新、注销、禁用账号、角色变更回归。
- JWT 中 tenant/user 与伪造 Header 冲突时，以 JWT 为准。
- 被移出工作区或账号禁用后，旧 Token 不再访问资源。

### 8.2 任务隔离

- 同 tenant 的 Alice/Bob 分别创建任务，只能列出、读取、取消、归档自己的任务。
- Bob 使用 Alice 的 run/session/thread/artifact/approval/file id 时全部得到 404。
- Worker 仍能执行 Alice 的后台任务并访问 Alice 的智能体、凭据、知识绑定和记忆。
- 不同 tenant 即使 user id、resource id 相同也完全隔离。

### 8.3 智能体隔离

- 同 tenant 的 Alice/Bob 可创建相同 name/version，目录互不可见。
- Bob 无法 get/update/validate/export/publish Alice 的 draft。
- 子智能体引用只在根智能体 owner 命名空间解析。
- Preview、Eval、Deployment、Quality、Trigger 的列表与详情均不泄露其他用户资源。
- 管理员可以管理 Bob 的角色，但默认仍无法读取 Bob 的任务或智能体。

### 8.4 迁移与部署

- 全量 Alembic upgrade/downgrade 在空库和带旧数据数据库上验证。
- 迁移前后记录数、hash、Artifact object key 和运行历史保持一致。
- 完整 Python 单元/集成测试、前端 typecheck/build、Docker Compose config 检查全部通过。
- 174 使用两个真实测试账号执行交叉访问矩阵；不连接公网不可达的业务 MCP 数据库。
- 174 固定由单独的 `migrate` 服务串行执行数据库迁移，业务 Worker 不自行运行迁移。
- 174 部署 3 个 Worker，验证同一队列的竞争消费不会重复执行 Run，并覆盖进程中断后的 lease/retry 恢复。

## 9. 发布与回滚

发布使用新的 AMD64 统一标签上传 Harbor，在 174 原目录修改版本后先运行唯一的 `migrate` 服务，再以 `docker compose up -d --no-build --wait --scale worker=3` 更新应用，不迁移主机。Worker 使用相同镜像和队列配置，不分配固定用户；每个 Worker 都从 Session 快照解析 `user_id` 与 `agent_owner_user_id`。切换前备份数据库和 compose env，记录旧镜像标签。灰度验证顺序是登录、智能体列表、任务列表、交叉 404、创建并运行无 MCP 的 Echo Agent、3 Worker 竞争消费与中断恢复、健康检查。

回滚应用时先恢复旧镜像；数据库迁移在新旧版本兼容窗口内保留新增列。只有确认不再需要回退后才执行约束清理。任何归属回填异常、跨用户可见、Worker 无法解析 owner 智能体或迁移记录不守恒，均立即停止切换。

## 10. 实施顺序

1. 增加统一 owner scope 类型、Repository 契约与迁移。
2. 完成草稿、已发布版本和子智能体 owner 解析。
3. 收紧 Preview/Eval/Deployment/Quality/Trigger 用户态入口。
4. 审计任务所有入口与子资源，补齐 owner 守卫。
5. 更新前端提示和成员管理隐私说明。
6. 完成双用户隔离与多 Worker 并发测试、回归、提交和 174 部署验证。
