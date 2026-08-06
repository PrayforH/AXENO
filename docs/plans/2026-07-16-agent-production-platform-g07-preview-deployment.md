# G07 短生命周期 Preview Deployment 完成审计

- **Goal：** G07 可恢复、可取消、可过期的 Preview Deployment
- **日期：** 2026-07-16
- **分支：** `feature/studio-preview-deployment`
- **基线提交：** `ca3eb77 feat: govern immutable Studio publication`
- **结论：** 通过；Studio Draft 已能创建不产生正式 AgentVersion 的测试身份 Preview

## 1. Preview 领域模型

Preview 是绑定某个 Draft 精确 revision 的短生命周期部署记录，持久化以下不可变事实：

- `draftId`、`draftRevision`；
- Manifest `contentHash` 与完整 Package `packageHash`；
- 租户、请求人、测试身份与 Preview 环境；
- 幂等键、TTL、过期时间与 fencing token；
- `queued → provisioning → ready` 及取消、失败、过期终态。

Preview 不写入 Agent Registry，也不创建正式 AgentVersion。Draft 后续发生 revision 或双 Hash
变化时，既有 Preview 会被标记为 stale，页面不会把旧环境误认为当前内容。

## 2. 队列、控制器与恢复

- API 创建 Preview 后先持久化记录，再投递 Redis 任务；
- Worker 通过可见性租约消费任务，控制器使用 CAS 和 fencing token 防止旧 Worker 覆盖新状态；
- Worker 崩溃或租约丢失后，任务可重新入队，新控制器可从 `provisioning` 恢复并收敛到终态；
- TTL reaper 将过期非终态 Preview 收敛为 `expired`；
- 取消请求先进入 `cancelling`，控制器保证最终进入 `cancelled`；
- provisioning 异常进入 `failed`，错误不会产生正式版本。

G07 的 provisioner 是明确的生命周期边界，不声称已经完成真实模型、Sandbox、MCP 与 Credential
连通性检查；这些 live preflight 能力由 G08 接管。

## 3. API 与权限

新增租户隔离的 Studio API：

```text
POST /v1/studio/previews
GET  /v1/studio/previews
GET  /v1/studio/previews/{preview_id}
POST /v1/studio/previews/{preview_id}/cancel
```

请求必须具备 `studio:preview`，服务端重新读取 Draft、校验 `expectedRevision`、执行实时 Studio
校验并计算双 Hash。相同租户和幂等键只产生一个 Preview；不同租户不能读取或取消对方资源。

## 4. UI 行为

- 只有 Draft 已保存、服务端校验通过且调用者可编辑时才允许创建 Preview；
- 页面展示真实状态、测试身份、Draft revision、TTL、过期时间及 stale 标记；
- 活跃且双 Hash 完全相同的 Preview 会复用；
- 已取消、失败或过期的 Preview 不会永久占用旧幂等键，可为同一 Draft 新建环境；
- 用户可刷新状态或发起取消，终态不再显示误导性的取消按钮；
- 生命周期仅在后端已存在 Preview 时进入 Preview 阶段，不再靠前端假状态推进。

## 5. 数据与迁移

Migration `0008_preview_deployments` 创建 Preview 表、租户幂等唯一约束和状态/过期索引。
已验证 `0007 → 0008 → 0007 → 0008`，表创建、回滚和重新升级均符合预期。

生产组合使用 PostgreSQL Repository 与 Redis Queue；测试组合提供相同契约的内存实现。Worker
维护循环同时执行任务推进与 TTL 回收。

## 6. 验收证据

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| 精确绑定 | Preview 固化 Draft revision 与双 Hash | 通过 |
| 测试身份 | API/UI 均明确 `test`、`preview`，未创建 AgentVersion | 通过 |
| 幂等 | 重复 POST 返回同一 Preview，数据库只有一行 | 通过 |
| stale | Draft r1 Preview 在保存 r2 后显示 stale | 通过 |
| 取消终态 | cancel 经控制器进入 `cancelled` | 通过 |
| TTL 终态 | reaper 将超时资源收敛为 `expired` | 通过 |
| 失败隔离 | provisioner 异常进入 `failed`，Registry 无新增版本 | 通过 |
| 崩溃恢复 | Redis visibility recovery 与新控制器恢复均覆盖 | 通过 |
| 进程重启 | PostgreSQL Preview 在重建容器后仍可查询并推进 | 通过 |
| 浏览器结果 | 创建、重复创建、Draft 更新、stale、取消完成真实交互 | 通过 |
| Console | 最终浏览器流程无 error | 通过 |

## 7. 自动化结果

```text
Frontend Vitest:             32 files, 141 passed
Next production build:       passed
Full Python suite:           475 passed, 1 skipped, 5 warnings
Ruff:                        passed
Pyright:                     0 errors, 0 warnings
Agent package check:         3 READY
Migration round trip:        passed
```

全量套件使用独立 `harness-g07-test` Compose 项目启动 PostgreSQL、Redis 和 MinIO。唯一跳过项仍是
显式 opt-in 的外部 Tavily Live 测试。

## 8. 范围审计

- 未把 G07 生命周期 hook 宣称为 G08 真实 Live Preflight；
- 未创建、覆盖或修改正式 AgentVersion；
- 未允许过期 revision 绕过服务端检查；
- 未将 Preview 凭据、Prompt、Skill 正文或 Secret 写入响应和审计；
- 未为 Preview 新建平行 Registry；
- 未把终态 Preview 错误复用为新的环境。
