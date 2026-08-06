# G04 持久化能力目录完成审计

- **Goal：** G04 持久化能力目录
- **日期：** 2026-07-16
- **分支：** `feature/studio-capability-catalog`
- **基线提交：** `7dcd2dc feat: mount Agent Studio API in production composition`
- **结论：** 通过；Catalog 已持久化并成为 Studio Compiler 的实时权威来源

## 1. 领域与持久化

能力目录现在覆盖：

- Model Route：逻辑 Route ID、模型清单、能力、Credential Reference、版本、启用状态；
- MCP Registration：逻辑 Reference、工具清单、网络/数据风险、Credential Reference、版本、启用状态；
- Policy Metadata：逻辑 Policy ID、风险、版本、启用状态；
- Execution Profile Metadata：逻辑 Profile ID、Sandbox Provider、允许的网络级别、风险、版本、启用状态。

`CapabilityCatalogRow` 以 tenant 为主键保存 revision、更新人、更新时间和版本化业务载荷。
Memory/PostgreSQL Adapter 运行相同 Contract：默认 Seed 幂等、租户隔离、revision CAS 和并发
两写一胜。

Draft 新增 `executionProfile` 逻辑引用，默认 `isolated-default`。Compiler 每次 validate、bundle
和 publish 都从当前 tenant 的 Repository Catalog 创建，不再持有启动时静态快照。

## 2. 管理 API

```text
GET    /v1/studio/catalog
PUT    /v1/studio/catalog
PUT    /v1/studio/catalog/{resource_type}/{resource_id}
GET    /v1/studio/catalog/{resource_type}/{resource_id}/impact
DELETE /v1/studio/catalog/{resource_type}/{resource_id}
```

- Admin/Owner 可创建、更新、整体替换和软禁用 Registration；
- Viewer/Member 只读，写操作返回 403；
- DELETE 是可审计软禁用，会提升 Entry Version 和 Catalog Revision；
- Impact 返回所有仍引用该资源的 tenant-scoped Draft ID；
- Path ID 与 Body ID 或资源类型不一致时拒绝；
- stale Catalog revision 返回 Conflict。

## 3. Secret 与输入边界

- Catalog Schema 没有 URL、Headers、API Key、Token 或 Secret Value 字段；
- Credential 只允许类似 `TAVILY_API_KEY` 的服务端 Secret Reference 名称；
- 额外 `apiKey`、任意 MCP `url` 和 Header 字段由 `extra=forbid` 拒绝；
- FastAPI 默认 422 会回显非法 `input`，本 Goal 已替换为脱敏错误信封，只返回
  type/location/message，不返回 input 或 ctx；
- API Trace 只记录 method/path，Audit 只记录状态码，均不读取 Request Body；
- 回归测试证明被拒绝的 Secret Value 和 URL 不出现在 422 或后续 Catalog 响应中。

## 4. 验收证据

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| 重启持久化 | 第一套 Production Container 修改目录并关闭，第二套恢复 revision 2 | 通过 |
| Seed 幂等 | 连续两次 GET 返回确定性相同 Catalog；已有配置不被默认值覆盖 | 通过 |
| Builder 只读 | Member 整体 PUT 和 Registration PUT 均为 403 | 通过 |
| Admin CRUD | 创建、更新、Impact、软禁用 Policy Registration | 通过 |
| 未知资源 | Compiler `*_unknown` fail closed | 通过 |
| 禁用资源 | Model/MCP/Policy/Execution Profile 返回明确 disabled issue | 通过 |
| 能力不兼容 | Model capability 与 Execution Profile network 检查失败 | 通过 |
| 影响检查 | 禁用被引用 Route 返回对应 Draft ID | 通过 |
| 发布版本冻结 | Catalog 修改前后 Registry 中 AgentVersion、Snapshot、Hash 完全相同 | 通过 |
| Secret 不泄漏 | Schema 拒绝 + 脱敏 422 + 响应/Trace/Audit 边界 | 通过 |
| 跨租户 | Catalog Repository 与 API 均使用服务端 tenant scope | 通过 |

Catalog 中集合型字段使用有序 tuple，而不是 frozenset，保证数据库往返、Seed 和 API JSON
输出确定性一致。

## 5. Migration 与自动化

线性 Revision：

```text
0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 -> 0007 (head)
```

执行并验证：空库 `upgrade head`、`downgrade 0006`、确认表删除、再次 `upgrade 0007`，以及
columns、PK、Check Constraint、Index 与 SQLAlchemy Model 的反射一致性。

```text
Focused API/security suite:  52 passed
PostgreSQL/restart suite:     4 passed
Full Python suite:          457 passed, 1 skipped, 5 warnings
Ruff:                        passed
Pyright:                     0 errors, 0 warnings
Agent package check:         3 READY
Alembic current/heads:       0007 (head)
```

唯一跳过项仍为需要显式 Live 开关的 Tavily 外部模型测试。

## 6. 范围审计

- 未保存明文 Secret；
- 未允许 Builder 输入任意 MCP URL；
- 未实现 gVisor；
- 未修改已发布 AgentVersion；
- 未改写旧 Migration；
- 未实现 Studio Web（G05）；
- 未提交环境文件、凭据、数据库数据或生成 Bundle。
