# G03 Studio API 主应用挂载完成审计

- **Goal：** G03 Studio API 主应用挂载
- **日期：** 2026-07-16
- **分支：** `feature/studio-api-composition`
- **基线提交：** `3c5e6c3 feat: persist Agent Studio drafts in PostgreSQL`
- **结论：** 通过；`/v1/studio` 已进入真实 FastAPI 主应用

## 1. 实现结果

Memory 与 Production Composition 现在都构造完整 `AgentStudioService`：

- Agent Draft Repository：Memory 使用 InMemory，Production 使用 PostgreSQL；
- Capability Catalog：当前使用服务端默认 Catalog；
- Compiler：`AgentDraftCompiler`；
- Publisher：复用已有 `AgentService.publish_bundle`；
- Clock/ID：由 Composition Root 注入；
- Identity/RBAC：复用 G01 的可信身份和细粒度权限。

`create_app()` 只挂载一次 Studio Router。Studio Service 从 `ApiContainer` 获取，不再通过额外
的 `app.state.agent_studio` 旁路注入。

## 2. API Contract

已挂载路径：

```text
GET  /v1/studio/capabilities
GET  /v1/studio/drafts
POST /v1/studio/drafts
GET  /v1/studio/drafts/{draft_id}
PUT  /v1/studio/drafts/{draft_id}
POST /v1/studio/drafts/{draft_id}/validate
GET  /v1/studio/drafts/{draft_id}/bundle
POST /v1/studio/drafts/{draft_id}/publish
```

本 Goal 没有实现 Web 发布按钮；publish API 是已有 Studio 生命周期能力与现有 Publisher
的组合，后续发布治理仍由 G06 完成。

## 3. 验收证据

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| 200/201 | capabilities、查询、校验、更新、下载、创建 | 通过 |
| 401 | 匿名与无 Service Token 的自报 Header | 通过 |
| 403 | member 调用 publish | 通过 |
| 404 | tenant-b 读取 tenant-a Draft | 通过，资源被隐藏 |
| 409 | 相同 expectedRevision 二次写入 | 通过 |
| 422 | 保存未知 Tool 后下载 Bundle | 通过，`draft_not_ready` |
| OpenAPI | 6 组 Studio Path 出现在主 Schema，创建响应含 201/422 | 通过 |
| Bundle 文件名 | `name-version-packageHashPrefix.zip` | 通过 |
| Bundle 类型 | `application/zip` | 通过 |
| Bundle 哈希 | ETag=归档 SHA256，另返回 Content/Package SHA256 | 通过 |
| 生产重启恢复 | 关闭第一套 Container，重建后经 HTTP 读取同一 Draft | 通过 |
| 资源关闭 | 两套 Production Container 的 Redis Client/DB Engine 均执行 close | 通过 |
| 现有 API | auth、AG-UI、runs 与全部 API 邻接测试 | 通过 |

Bundle 响应新增明确的三类哈希，避免混淆：

- `ETag`：实际下载 ZIP 字节的 SHA256；
- `X-Agent-Content-SHA256`：规范化 Agent 源内容哈希；
- `X-Agent-Package-SHA256`：可复现 Package 哈希，也用于文件名短后缀。

## 4. 自动化验证

```text
Studio API Contract:        6 passed
Production restart API:     1 passed
Adjacent API/composition:  73 passed
Full Python suite:         443 passed, 1 skipped, 5 warnings
Ruff:                       passed
Pyright:                    0 errors, 0 warnings
Agent package check:        3 READY
Alembic head:               0006
```

唯一跳过项仍为需要显式 Live 开关的 Tavily 外部模型测试。全量测试使用临时 PostgreSQL、
Redis 和 MinIO，并按测试契约创建 Bucket。

## 5. 范围审计

- 未修改 Studio Web 或浏览器 localStorage 草稿（G05）；
- 未把能力目录持久化（G04）；
- 未新增 Migration；
- 未改变 Agent Runtime、Sandbox、MCP Credential 或审批策略；
- 未提交 Secret、环境文件、数据库数据或 Bundle；
- API 错误继续使用 Harness 统一 `{"error": {"code", "message"}}` 信封；FastAPI 输入
  Schema 校验仍保持框架标准 422，业务 Bundle 422 使用统一信封。
