# G06 授权发布与审计闭环完成审计

- **Goal：** G06 授权发布、不可变版本与审计闭环
- **日期：** 2026-07-16
- **分支：** `feature/studio-publish-audit`
- **基线提交：** `84d53d9 feat: connect Agent Studio web to control plane`
- **结论：** 通过；Studio Draft 已能经生产门禁发布为不可覆盖 AgentVersion

## 1. 发布闭环

Studio 没有另建 Registry 或 Package 体系，继续复用现有 `AgentService.publish_bundle`：

1. 校验调用者的 `studio:publish`；
2. 以 `expectedRevision` 拒绝过期发布请求；
3. 从租户实时 Catalog 重新编译，执行 production package check；
4. 复验每个固定版本 Sub Agent 的 Registry 状态和 Studio 发布哈希；
5. 将 Bundle 交给 `AgentService` 写入不可变 Agent Registry；
6. CAS 回写 Draft 的 published version、manifest hash 和 package hash；
7. 写入脱敏领域审计；
8. 返回不含 Prompt、Skill 文件和 Snapshot 正文的最小发布结果。

`admin`/`owner` 有发布权限，`member`/`viewer` 没有。UI 仍要求先保存并通过服务端检查，
服务端继续作为最终权威门禁，不能靠启用按钮绕过。

## 2. 不可变、幂等与依赖

- 相同 Draft 内容、相同版本重复发布返回同一个 AgentVersion，不创建重复 Registry 行，也不
  再提升 Draft revision；
- 相同 `name@version` 但 Manifest 或 Package 内容不同，返回稳定 `version_conflict`；
- Draft 同时记录 `publishedHash` 和 `publishedPackageHash`。只比较 Manifest Hash 会漏掉
  README、评测等 Package 变化，因此 UI 与服务端幂等判断都使用双 Hash；
- 未发布、非 Published 状态的 Sub Agent 返回 `subagent_not_published`；
- Studio Draft 记录的子版本 Hash 与 Registry 不一致时返回 `subagent_version_drift`；
- 依赖问题同时进入 Validate 和 Publish，不能出现“页面检查通过、发布才静默失败”。

发布后的 AgentVersion 继续是不可变完整 Snapshot；后续 Catalog 修改或 Draft 修改不会改写
旧版本。Draft 可以继续编辑，但页面会显示“存在历史发布版本”，直到升版本并发布新内容。

## 3. 领域审计与数据最小化

每次发布尝试新增 `studio.publish` AuditEntry：

```text
actor: tenant_id + user_id
resource: agent_draft + draft_id
success: name, version, manifest_hash, package_hash, draft_revision,
         dependency refs, idempotent
denied:  name, version, draft_revision, stable error_code
```

审计不记录 System Prompt、Skill instructions、Skill 文件正文、Bundle、Credential、Secret、
Header 或异常原文。API 的发布响应也不再返回完整 Agent Snapshot，只返回版本身份和双 Hash。
请求级 Audit 仍保留 HTTP 状态，形成领域事实与入口事实两层证据。

## 4. UI 状态

- 发布按钮仅对 Admin/Owner、已保存且服务端检查通过的 Draft 启用；
- 发布成功后目录显示真实 `已发布 version · revision`；
- 标题区显示不可变版本、Manifest Hash 前缀和当前/历史状态；
- 生命周期进入 Version，运行契约显示真实已发布版本；
- 重复发布显示重新核验，不产生新 revision；
- 同版本不同内容显示专用冲突条，明确要求修改版本号，未误报为普通 revision 冲突；
- Member 的发布按钮保持禁用，后端即使直接调用也返回 403。

## 5. 验收证据

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| Owner/Admin 发布 | Owner API/浏览器发布 200；RBAC 覆盖 Admin `studio:publish` | 通过 |
| Member 禁止 | Member 发布返回 403 `permission_denied` | 通过 |
| 生产门禁 | Catalog 实时编译 + production Bundle 解包/来源/Package 复验 | 通过 |
| Draft 回写 | revision 1 → 2，回写 version、manifest hash、package hash | 通过 |
| 幂等 | 重复发布返回同一响应，Registry 不重复，Draft 保持 revision 2 | 通过 |
| 不可覆盖 | 内容变化但沿用 0.1.0 返回 409 `version_conflict` | 通过 |
| 依赖未发布 | Validate/Publish 均返回 `subagent_not_published` | 通过 |
| 依赖漂移 | Studio Hash 与 Registry Hash 不同返回 `subagent_version_drift` | 通过 |
| 审计成功/失败 | `studio.publish` 同时覆盖 success、idempotent、denied | 通过 |
| 审计脱敏 | Sentinel Prompt/Skill file 不出现在 Audit JSON | 通过 |
| 响应最小化 | Publish 响应没有 `snapshot` | 通过 |
| 浏览器结果 | 门禁、成功、目录、重复幂等、内容冲突均完成真实交互 | 通过 |
| Console | 最终干净浏览器发布流程无 error/warn | 通过 |

## 6. 自动化结果

```text
Focused Studio/API suite:    18 passed
Frontend Vitest:             32 files, 139 passed
Next production build:       passed
Full Python suite:           463 passed, 1 skipped, 5 warnings
Ruff:                        passed
Pyright:                     0 errors, 0 warnings
Agent package check:         3 READY
```

全量套件使用独立 `harness-g06-test` Compose 项目启动 PostgreSQL、Redis 和 MinIO；测试完成后
容器、网络和数据卷均已删除。唯一跳过项仍是显式 opt-in 的外部 Tavily Live 测试。

## 7. 范围审计

- 未实现 G07 Preview Deployment；
- 未把静态 Schema 校验宣称为 G08 Live Preflight；
- 未允许覆盖或修改既有 AgentVersion；
- 未向 Audit/API 发布响应写入 Prompt、Secret、文件正文或完整 Snapshot；
- 未新增平行 Registry、发布表或不必要 Migration；
- 未保留测试容器、测试卷、下载 Bundle、账户或本地运行数据。
