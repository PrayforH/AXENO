# G01 Studio 身份与细粒度 RBAC 完成审计

- **Goal：** G01 Studio 身份与细粒度 RBAC
- **日期：** 2026-07-16
- **分支：** `feature/studio-rbac`
- **基线提交：** `37c8a10 docs: establish agent platform execution baseline`
- **结论：** 通过；Studio Router 仍未挂载，未新增数据库表

## 1. 实现结果

Studio API 不再读取 `request.state.studio_actor`。所有 Actor 均由 Harness 已验证的
`Identity` 映射产生，tenant 和 user 只取自服务端认证结果：

- JWT：使用签名 Access Token 对应的 User 和 Membership；
- 服务身份：仅在 Harness Service Token 验证成功后接受 tenant/user Header；
- 未认证请求：401；
- 已认证但权限不足：403 `permission_denied`。

权限矩阵：

| Role | read | write | preview | publish | deploy |
| --- | --- | --- | --- | --- | --- |
| viewer | 是 | 否 | 否 | 否 | 否 |
| member | 是 | 是 | 是 | 否 | 否 |
| admin | 是 | 是 | 是 | 是 | 是 |
| owner | 是 | 是 | 是 | 是 | 是 |

当前已有路由按能力拆分：查询与 Bundle 下载要求 read，Draft 创建/修改/校验要求
write，发布要求 publish。preview 和 deploy 权限先进入统一 RBAC，实际端点由后续 Goal
实现。

## 2. 验收证据

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| JWT 产生可信 Actor | 真实注册获取 JWT 后创建 Draft | 通过 |
| 服务身份产生可信 Actor | Service Token + tenant/user 创建、校验、下载、发布 | 通过 |
| 401 / 403 | 匿名和伪造 Header 返回 401；member 发布返回 403 | 通过 |
| 四角色权限矩阵 | 20 组参数化 Studio 权限测试 | 通过 |
| tenant/user 不可伪造 | JWT 下冲突 Header 被忽略；请求体注入字段返回 422 | 通过 |
| 现有权限无回归 | viewer/member/admin/owner 的 task 与 agent 权限参数化测试 | 通过 |
| 非目标约束 | Router 未挂载；无 migration 和 Schema 修改 | 通过 |

## 3. 自动化验证

```text
Targeted Studio/Auth/API: 45 passed
G01 focused suite:        34 passed
Full Python suite:        434 passed, 1 skipped, 5 warnings
Ruff:                     passed
Pyright:                  0 errors, 0 warnings
Agent package check:      3 READY
git diff --check:         passed
```

全量测试使用临时 PostgreSQL、Redis、MinIO 默认端口服务；MinIO Bucket 按测试契约创建。
所有 `harness-g01-*` 临时容器已删除。唯一跳过项仍为需要显式 Live 开关的 Tavily 外部
模型测试。

## 4. 范围审计

- 没有挂载 `harness.studio.api.router` 到主应用；
- 没有新增 Draft 表或 Alembic migration；
- 没有加入自定义角色或前端权限逻辑；
- 没有提交 Secret、环境文件或生成的 Agent Bundle；
- Web、Sandbox、模型运行路径没有改动。

G01 的完成状态只证明可信身份映射和授权边界，不代表 Agent Studio 已对用户开放。Draft
持久化由 G02 负责，Composition Root 与 API 正式挂载由 G03 负责。
