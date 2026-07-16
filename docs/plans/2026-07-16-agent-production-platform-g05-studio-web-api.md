# G05 Studio Web API 化完成审计

- **Goal：** G05 Studio Web 从浏览器草稿迁移到 API
- **日期：** 2026-07-16
- **分支：** `feature/studio-web-api`
- **基线提交：** `7c6626c feat: persist and govern Studio capability catalog`
- **结论：** 通过；`/studio/agents` 已以租户 Studio API 为唯一主数据源

## 1. Web 数据边界

Agent Studio 不再使用静态 Agent 列表或 localStorage 作为主数据：

- Next BFF `/api/studio/[...path]` 使用现有 HttpOnly 登录会话代理 `/v1/studio`；
- BFF 保留 Query、ETag、Content-Disposition 和 Bundle Hash Header；
- Typed Client 覆盖 Draft 列表、详情、创建、全量替换、校验、能力目录和 Bundle 下载；
- UI 中的 Draft 行、revision、发布版本、Model、Tool、MCP 和 Policy 选项均来自服务端；
- API 错误使用带 status/code 的类型化错误，不把网络失败伪装成空列表；
- Endpoint、Credential、Header 和 Secret 仍不进入浏览器 Draft。

服务端返回的 Skill 文件、模型能力要求、Execution Profile、评测标签和 Workspace 选项都可
无损往返，避免 Web 保存时静默丢字段。

## 2. 草稿迁移与并发

旧 key `harness-agent-studio-draft` 只用于一次性迁移：

1. 合法旧草稿先创建服务端 Draft，再以 revision CAS 写入完整 Spec；
2. 创建后立即记录 `pending:<draftId>`；若第二步断网，下次继续同一个 Draft，不会重复创建；
3. 完成后删除旧正文并记录最终 draftId；
4. 非法 JSON 明确丢弃并记录 marker；
5. API 离线时保留唯一浏览器副本，待恢复后重试。

正常编辑使用 `expectedRevision`。409 时页面保留本地输入，显示显式冲突条，并提供“加载
最新版本”操作；不会自动覆盖另一窗口的修改。

## 3. 页面状态与权限

- Loading：认证完成后独立显示控制面恢复状态；
- Empty：租户无草稿时列表为 0，并明确提示创建第一个草稿；
- Error：Studio API 失败显示可重试错误页，不回退假数据；
- Unauthorized：未登录访问由 `AuthProvider` 跳转 `/login`；
- Forbidden：Viewer 的完整编辑 fieldset、创建、保存和检查按钮禁用，并显示只读说明；
- Member：允许创建、编辑、保存和校验，但发布保持禁用；
- Admin/Owner：本 Goal 仍不提前开放发布，等待 G06 的发布治理和审计闭环；
- Bundle：已保存 Draft 可下载，文件名取服务端 Content-Disposition。

窄屏保留品牌与工作区切换，将目录和生命周期压缩为紧凑导航；编辑章节横向滚动，不把
主表单挤成不可操作的双栏。

## 4. 验收证据

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| 无假列表 | 空租户浏览器显示 0；代码和测试禁止旧 helper/echo 示例 | 通过 |
| 刷新恢复 | 创建后 revision 2；刷新重新 GET Draft 并显示同一行 | 通过 |
| 创建/保存 | POST 201、PUT 200，UI 显示服务端 revision | 通过 |
| 服务端校验 | Validate 200，页面显示“结构检查通过” | 通过 |
| Bundle 下载 | BFF 与 API 均返回 200，页面进入“下载已开始”状态 | 通过 |
| 并发冲突 | 两个独立标签页从 revision 2 编辑；首个保存到 r3，第二个 PUT 409 | 通过 |
| 冲突保留输入 | 第二个标签页仍保留“舆情研判 Agent B”；加载最新后恢复 Agent A/r3 | 通过 |
| 迁移幂等 | 单测覆盖首次导入、重复调用、创建失败、替换失败续传、非法 JSON | 通过 |
| 未登录 | 直接访问 Studio 自动跳转 `/login` | 通过 |
| 角色边界 | Auth membership 驱动只读 fieldset 和按钮；发布始终未提前启用 | 通过 |
| 错误状态 | 类型化 API Error + 独立 Error/Reload UI | 通过 |
| 390px 窄屏 | 真实 390×844 浏览器检查，标题、操作、章节和能力卡可用 | 通过 |
| Console | 桌面、冲突和窄屏检查均无 error/warn | 通过 |

## 5. 自动化结果

```text
Frontend Vitest:             32 files, 138 passed
Next production build:       passed
Studio API integration:      9 passed
Ruff:                        passed
Pyright:                     0 errors, 0 warnings
Browser API flow:            401 -> login/register -> create/save/refresh/validate/download
Concurrent browser flow:     PUT 200 -> stale PUT 409 -> reload revision 3
```

真实浏览器使用隔离端口 `localhost:3100` 和本地 Fake Runtime API `127.0.0.1:18000`；验收后
进程和临时浏览器标签均已关闭，没有改动现有 3000/8000 环境。

## 6. 范围审计

- 未在浏览器保存主 Draft 数据；
- 未保留假 Agent 目录；
- 未把 Secret、Token、任意 MCP URL 或 Header 暴露给 Builder；
- 未绕过服务端 tenant scope、RBAC 或 revision CAS；
- 未提前实现 G06 Publish、G07 Preview 或 G08 Live Preflight；
- 未提交 `.next`、下载 Bundle、登录信息或本地运行数据。
