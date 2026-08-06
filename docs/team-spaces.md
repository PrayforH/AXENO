# 个人空间与团队共享空间

Agent Studio 把“可复用定义”和“用户运行记录”放在不同的安全边界中。

## 资源模型

- 个人 Agent 版本的主键仍为 `(tenant_id, owner_user_id, name, version)`。
- 团队空间只保存对已发布、不可变 Agent 版本的授权引用，不复制 Agent，也不改变所有者。
- 团队知识库授权保存 Knowledge Base reference；运行时仍固定具体 snapshot，并在每次检索时重新检查空间授权。
- 从团队空间复制 Agent 会在接收者个人作用域创建相同内容哈希的版本；不会复制 MCP 凭据、部署、Session、Run、文件或记忆。

## RBAC

| 角色 | 成员管理 | 共享 Agent | 共享知识库 | 运行 Agent |
| --- | --- | --- | --- | --- |
| Owner | 是 | 仅自己的 Agent | 是 | 是 |
| Admin | 是，不能管理 Owner/其他 Admin | 仅自己的 Agent | 是 | 是 |
| Contributor | 否 | 仅自己的 Agent | 否 | 是 |
| Viewer | 否 | 否 | 否 | 由 `runnableByViewer` 决定 |

团队空间至少保留一位 Owner。非成员查询空间时返回 404，避免泄露空间是否存在。

## 运行隔离

共享 Agent 启动任务时，Session 同时固定：

- `user_id`：任务所有者，也是 MCP 凭据、输入文件和长期记忆的解析主体；
- `agent_owner_user_id`：不可变 Agent 定义的所有者；
- `team_ids`：授权来源，用于运行时重新检查团队知识库访问；
- `agent_name + agent_version`：本次任务固定的发布版本。

因此成员可以运行同一个共享 Agent，但无法读取彼此的线程、Run、审批、Artifact、工作区快照或记忆。撤销共享或移除成员后，新 Session 和既有 Session 的后续 Run 都会被阻止，但已经产生的审计和任务事实不会被篡改。

## MCP 凭据

MCP 凭据永远按 `ExecutionIdentity.user_id` 解析，不按 Agent 创建者解析。共享包只包含 MCP server reference 和 required keys。使用者缺少凭据时，运行按现有流程失败并提示配置，不会回退使用创建者的秘密。

## API

- `GET/POST /v1/spaces`
- `GET/PUT/DELETE /v1/spaces/{space_id}/members`
- `GET/POST/DELETE /v1/spaces/{space_id}/agents`
- `POST /v1/spaces/{space_id}/agents/{owner}/{name}/{version}/fork`
- `GET/POST/DELETE /v1/spaces/{space_id}/knowledge`

Web 控制面位于 `/studio/spaces`。
