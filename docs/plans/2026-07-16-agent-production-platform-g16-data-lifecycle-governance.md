# G16 数据保留、导出、删除与合规治理验收记录

## 结论

Harness 已建立 tenant-scoped 数据生命周期控制面。RetentionPolicy、LegalHold 与耐久
DataLifecycleJob 统一驱动对象存储、Claude SDK Session、长期记忆、Langfuse 和 PostgreSQL；
导出/删除都能查看逐 Adapter 进度，部分失败保持可重试断点，不把外部系统的“已受理”误报为
“已删除”。

## 已完成范围

- 新增 RetentionPolicy、LegalHold、DataLifecycleJob、AdapterResult 模型，PostgreSQL Repository、
  fencing/CAS 与 `0013` migration；migration 已验证全新 upgrade、downgrade 到 `0012`、再次 upgrade；
- 提供 tenant、user、session、agent 范围的导出/删除 API；owner/admin 可管理全租户，member/viewer
  只能创建和读取自己的 user/session 请求；所有读取与下载都再次绑定认证 tenant；
- Worker 每个 UTC 日为已配置保留策略的租户幂等创建 Retention Job，并独立 reconcile；管理员也可
  立即触发一次；
- Legal Hold 在 Job 创建和 Worker 执行两个时点检查，消除“入队后才添加 Hold”的竞态；session
  会解析为其 user 和 agent 关联范围，tenant Hold 覆盖全部范围；创建、释放和拒绝均写审计；
- 对象删除按 Object Store → SDK Session → Memory → Langfuse → PostgreSQL 排序；任何破坏性
  Adapter 失败立即停止后续步骤，保留 PostgreSQL 索引供重试继续定位外部数据；
- Langfuse 通过 Public API Basic Auth 删除 Trace，并在删除后 GET 验证 404；仍可见时记录
  `ExternalDeletionPendingError`，等待后续重试。Langfuse 官方说明删除为异步操作，通常需要等待
  后再查询确认：[Data Deletion](https://langfuse.com/docs/administration/data-deletion)；Public API 使用
  project public/secret key Basic Auth：[Public API](https://langfuse.com/docs/api-and-data-platform/features/public-api)；
- PostgreSQL Adapter 删除 Session、Run/Event、Approval、Artifact 元数据、Workspace、输入、Eval
  和关联质量事实；审计、AgentVersion、Deployment Environment/Snapshot 等必要运营与合规证据保留；
- 导出生成 ZIP Artifact，包含 manifest 与分 Adapter JSON；密钥字段和正文中的 token/API key
  会被脱敏，下载文件名保留 `.zip`，跨租户对象无法读取；
- Agent Studio 新增“数据”页与第四个左侧 Tab：保留周期、Legal Hold、级联 Adapter 轨迹、失败
  重试和安全下载在同一视图；账户设置增加“我的数据”自助入口；普通用户不显示租户治理数据；
- 页面沿用 Studio 的纸面控制台视觉，签名元素是级联删除链：它表达真实执行顺序和断点，而不是
  装饰性流程图；桌面和窄屏均提供响应式布局、键盘焦点与无渐变视觉约束。

## 一致性与安全不变量

1. PostgreSQL 永远是破坏性链路最后一个 Adapter；外部删除未确认前不能丢失本地 trace/object 索引；
2. Adapter 成功事实不会在删除重试时重复执行；失败和未开始步骤继续，导出重试则从头生成一致快照；
3. Job、Hold、Policy、下载和 Adapter 查询均携带 tenant 条件；不存在仅凭全局 ID 读取的路径；
4. Legal Hold 优先于 Retention 与显式删除，且 Worker 执行前必须重新确认；
5. 外部系统的 200/202 仅表示删除已受理，只有后续查询不可见才计为成功；
6. 审计与部署所需元数据不进入普通保留删除；业务导出可包含审计摘要，但 Secret 必须脱敏；
7. 策略修改使用 revision CAS，Job 使用 tenant + idempotency key 与 fencing token。

## 验收证据

- Ruff 与 Pyright 全绿；
- 后端全量：585 passed、4 skipped、5 个既有依赖弃用 warning；新增生命周期定向测试 11 项通过；
- PostgreSQL 真存储验证：Repository tenant 隔离、幂等、fencing；过期 Session 被删除，同时 Audit、
  Deployment Environment 与运营 Quality Rule 保留；
- Langfuse MockTransport 验证：DELETE 返回 202 且 GET 仍为 200 时失败可见，下一次 GET 404 后才成功；
- 删除链故障注入验证：Object Store 成功、Langfuse 失败时 PostgreSQL 保持 pending，重试只继续失败
  和未开始步骤；
- Legal Hold 验证：创建时阻止删除和每日 Retention；Job 入队后增加 user Hold，也会在 session 删除
  执行前收敛为 `LegalHoldActive`，Adapter 零调用；
- 导出验证：ZIP 只包含 manifest/Adapter 数据，跨 tenant 下载返回 NotFound，Authorization 与
  token-like 内容被脱敏；
- 前端 150 tests passed，Next.js production build passed；
- 浏览器实际验证 `/studio/data`：注册/登录、四 Tab、默认 r0 策略、Legal Hold 表单、用户导出、
  排队状态和五段 Adapter 级联轨迹均正常；
- MinIO 实例读写通过；Alembic `0012 ↔ 0013` 往返迁移通过。

## 运行边界

- 默认策略是 revision 0 的合成基线；只有保存过策略的 tenant 会被每日调度器枚举，首次进入页面后
  可保存或手动执行；G17 应将调度延迟和未执行策略纳入 SLO/告警；
- Artifact 表当前没有独立创建时间，保留删除按所属 Run/Session 的时间归属；需要“文件独立 TTL”时
  应增加对象级时间索引，而不是从对象名推断；
- Langfuse 删除可能需要约 15 分钟完成，Job 会显示 partial failure 并由重试收敛；G17 应增加带退避的
  自动重试、最大等待时间和待删除 Trace 指标；
- Memory/SDK Session 删除以本地持久化实现为事实源；未来接入独立向量库或远程 Session Store 时，
  必须新增 Adapter，不能让 PostgreSQL Adapter 代替外部确认；
- 审计与部署证据的最终法定保留期限仍需由组织政策确认；当前实现采取“普通删除不移除”的保守策略。
