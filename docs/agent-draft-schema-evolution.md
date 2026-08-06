# Agent Draft JSON Schema 演进策略

Agent Draft 在 PostgreSQL 中使用“查询信封 + 版本化 JSON”存储：

- `tenant_id + draft_id`：租户隔离的复合主键；
- `name / revision / updated_at`：查询、排序和原子并发控制字段；
- `schema_version`：JSON 载荷版本，当前为 `1`；
- `payload`：`AgentDraft.model_dump(mode="json", by_alias=True)` 的完整业务对象。

## 兼容规则

1. **新增可选字段**：给 Pydantic 模型提供确定性默认值，不提升 Schema Version；旧载荷可直接读取。
2. **重命名、拆分或语义变化**：先实现 `N -> N+1` 的纯函数 Upcaster 和回归样例，再提升写入版本；读取时逐级升级，禁止跳级。
3. **删除字段**：至少跨一个发布周期保留 Upcaster；确认所有存量载荷可升级后再删除旧读取逻辑。
4. **未知未来版本**：服务端 fail closed，不猜测字段含义，也不覆盖原载荷。当前实现会明确抛出不支持的 Schema Version。
5. **信封一致性**：读取时校验 tenant、draft ID、revision、name、updated time 与 JSON 一致；不一致视为数据损坏。
6. **并发迁移**：Upcast 不能绕过 `expectedRevision`；如需回写升级后的 JSON，必须使用同一 revision CAS，并允许其他 Writer 获胜。

## 凭据边界

Draft Schema 只能保存平台能力引用，例如 Model Route ID、MCP Server Reference 和 Permission
Policy 名称。它不提供 API Key、Token、Secret 或任意 MCP Endpoint 字段。真实凭据由服务端
Credential Provider 管理，在运行时按引用解析，不进入 Draft JSON、Bundle、API 响应或审计
详情。

System Prompt 与 Skill 属于 Agent 源代码，会保存在 Draft 中。平台和业务开发者不得把凭据
粘贴进 Prompt/Skill；未来的 Secret Scanner 属于发布门禁增强，不能替代服务端引用模型。

## 版本升级检查清单

- 为旧版本固定一份脱敏 JSON Fixture；
- 添加 Upcaster 单元测试和 PostgreSQL 读取测试；
- 验证升级前后编译出的有效契约语义不变，或明确记录有意变更；
- 验证 stale revision 和并发更新仍只有一个 Writer 成功；
- 执行 Alembic upgrade/downgrade/upgrade；
- 在生产开始写新版本前，确认所有 Reader 已部署兼容代码；
- 禁止通过修改旧 Alembic Revision 偷渡 Schema 变化。
