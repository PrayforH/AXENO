# G02 Agent Draft PostgreSQL 持久化完成审计

- **Goal：** G02 Agent Draft PostgreSQL 持久化
- **日期：** 2026-07-16
- **分支：** `feature/studio-drafts-db`
- **基线提交：** `6a86521 feat: secure Agent Studio with trusted RBAC`
- **结论：** 通过；Migration Head 为 `0006`，Studio Router 仍未挂载

## 1. 实现结果

新增 tenant-scoped `PostgresAgentDraftRepository` 和 `AgentDraftRow`：

- 复合主键：`tenant_id + draft_id`；
- CAS 列：`revision`；
- 查询信封：`name / updated_at`；
- 演进信封：`schema_version + payload`；
- 数据约束：revision 和 schema version 必须为正数；
- 索引：tenant + name、tenant + updated time；
- 生产 `ApiContainer.agent_drafts` 使用 PostgreSQL Adapter；
- 内存 Container 继续使用相同 Port 的 InMemory Adapter。

领域 Port 保留在 `harness.studio.repositories`，PostgreSQL Adapter 位于
`harness.storage.studio_repository`，避免 Studio 领域层依赖 SQLAlchemy。主应用没有挂载
Studio Router，G02 只让生产 Composition 可以构造持久化仓储。

## 2. 验收证据

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| create/get/list/replace tenant scope | InMemory/PostgreSQL 运行同一 Contract | 通过 |
| 跨租户同名和相同 Draft ID | tenant-a/tenant-b 保存相同 ID 与 name，分别可读 | 通过 |
| stale revision | 两种 Adapter 均返回 Conflict | 通过 |
| 原子并发更新 | 两个 Writer 同时 CAS，恰好一个成功、一个 Conflict | 通过 |
| 重启持久化 | Dispose 第一组 Engine，用新 Engine/Repository 恢复原对象 | 通过 |
| Schema 演进 | 版本 1 载荷；未知版本 fail closed；策略文档已提交 | 通过 |
| Migration | 空库完整回放、0006 downgrade、0005→0006 upgrade | 通过 |
| Model/DB 一致 | columns、PK、checks、indexes 反射比较 | 通过 |
| 生产 Composition | 单元测试断言 PostgreSQL Adapter | 通过 |

Schema 演进权威说明见 `docs/agent-draft-schema-evolution.md`。Draft 只保存 Model Route、MCP
Server、Policy 等服务端能力引用，不新增 Key、Token、Secret 或任意 Endpoint 字段。

## 3. Migration 审计

新增唯一线性 Revision：

```text
0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006 (head)
```

验证路径：

1. 空 Schema 执行 `alembic upgrade head`；
2. `alembic current` 为 `0006 (head)`；
3. `alembic downgrade 0005`，确认 `agent_drafts` 不存在；
4. 再执行 `alembic upgrade head`；
5. 反射比较表字段、复合主键、两个 Check Constraint 和两个 Index。

审计时发现历史 `0001` 会调用当前 `Base.metadata.create_all()`，因此空库全历史回放可能提前
创建未来表。`0006` 保留显式冻结的建表定义，同时在表已存在时幂等跳过；这兼容空库回放，
也能在真实 0005 数据库中显式创建新表。该历史行为没有在 G02 中重写旧 Revision。

## 4. 自动化验证

```text
Shared/adjacent focused suite: 16 passed
Full Python suite:             440 passed, 1 skipped, 5 warnings
Ruff:                          passed
Pyright:                       0 errors, 0 warnings
Agent package check:           3 READY
Alembic current/heads:         0006 (head)
git diff --check:              passed
```

唯一跳过项仍为需要显式 Live 开关的 Tavily 外部模型测试。测试使用临时 PostgreSQL、Redis
和 MinIO；MinIO Bucket 按测试契约创建。

## 5. 范围审计

- 未挂载 Studio Router；
- 未实现 Studio API Composition（G03）；
- 未修改 Agent Publish、Preview 或 Deployment 语义；
- 未在 Draft Schema 中加入 Secret 字段；
- 未修改旧 Alembic Revision；
- 未产生第二个 Migration Head；
- 未提交数据库数据、环境文件、凭据或生成 Bundle。
