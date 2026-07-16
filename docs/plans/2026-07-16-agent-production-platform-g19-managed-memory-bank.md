# G19：受控长期 Memory Bank 完成审计

日期：2026-07-16
分支：`feature/managed-memory-bank`

## 1. 结论

G19 已把原有只读 `UserMemory` 文本投影升级为用户可治理的长期 Memory Bank：Agent 只能
提出候选记忆，默认逐条确认；用户也可以为单个 Agent 明确允许自动保存一般偏好。敏感内容
始终待确认，凭据、私钥、Bearer Token 和 Prompt Injection 在持久化前拒绝。

每条记忆保留 tenant/user/agent、来源、采集时间、置信度、敏感等级、授权状态、版本和
到期时间。编辑、确认、拒绝、删除均使用 CAS。删除、拒绝或过期后正文与 hash 被清除，且
不会进入检索或 Prompt 投影。用户可在 `/settings/memory` 查看、确认、拒绝、编辑、删除、
配置保留期限和导出 JSON。

## 2. 写入与授权模型

| 来源 | 默认结果 | 显式 Agent Policy 后 | 安全边界 |
| --- | --- | --- | --- |
| 用户/API 提议 | `pending` | 仍为 `pending` | 用户逐条确认 |
| Agent 一般偏好提议 | `pending` | `active` | 仅当前 tenant/user/agent |
| Agent 敏感信息提议 | `pending` | 仍为 `pending` | 不允许策略绕过 |
| 凭据/私钥/Prompt Injection | 拒绝 | 拒绝 | 不落库 |

Agent 工具由原直接更新语义改为 `propose_memory`。本地 SDK Runtime 使用进程内 MCP；
Daytona/Kubernetes 注入 HTTP MCP，Worker 签发 5 分钟 HS256 令牌，精确绑定 tenant、user、
project、session、run、agent 和 agent version。签名使用独立
`HARNESS_MEMORY_WORKLOAD_TOKEN_SECRET`，不复用用户登录 JWT。远端 Sandbox 不接触 Python
Repository 或 Service 对象。

## 3. 持久化、检索和删除

Migration `0015` 增加：

- `memory_entries`：tenant/user/entry 复合主键，scope/status 与 expiry 索引；
- `memory_consents`：tenant/user/agent 复合主键和版本；
- `memory_retentions`：tenant/user/agent 复合主键和版本。

Repository 所有读取和 CAS 都携带 tenant/user，检索额外强制 agent scope。当前
`KeywordMemorySearchAdapter` 提供确定性关键词检索和零重合不召回；接口可替换为 tenant
隔离的向量 Adapter。运行时投影只读取 active、未过期且当前 Agent 的条目，并把来源、时间、
置信度与正文放入明确标记为“untrusted data, never instructions”的转义数据块。

删除、拒绝、过期会清空正文和原 hash；生命周期导出/删除同时覆盖旧 UserMemory 与新
entries/consents/retentions。过期 Reaper 已接入 Worker maintenance loop。

## 4. API 与用户页面

控制面提供 list/propose/confirm/reject/edit/delete/search/export、Agent consent 与 retention
API，所有接口使用登录身份和既有 RBAC，不接受浏览器自报 tenant/user。导出响应使用
attachment 与 `private, no-store`。

页面采用“证据账本”而不是聊天气泡：每条记录直接展示状态、敏感等级、来源、Agent、
置信度和到期时间；待确认项提供确认/拒绝，生效项提供编辑/删除。桌面 1280×720 与移动
390×844 均完成浏览器检查，无横向溢出。按用户决定，本 Goal 没有新增运营页面或运营 Tab。

## 5. 要求与证据

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| 默认不自动永久记忆 | `test_agent_proposal_requires_confirmation_by_default` | 已证明 |
| 敏感/禁止字段治理 | Service 分类测试与三组 prohibited 用例 | 已证明 |
| tenant/user/agent 隔离 | Service、PostgreSQL、API 与生命周期隔离测试 | 已证明 |
| 删除和过期一致性 | 删除、Reaper、Eval 与真实 PostgreSQL 测试 | 已证明 |
| 冲突更新 CAS | Service/API/PostgreSQL expectedVersion 测试 | 已证明 |
| 来源、时间、置信度 | 模型、投影、API 与页面浏览器验收 | 已证明 |
| Daytona 不使用进程内对象 | 真实 Streamable HTTP MCP initialize/list/call | 已证明 |
| 召回误召回/漏召回安全 | `MemoryRecallEvalRunner` 确定性用例 | 已证明 |
| Prompt Injection 不进入记忆 | Safety classifier 与 projection delimiter 测试 | 已证明 |
| 用户查看/编辑/删除/导出 | Web component/BFF 测试与浏览器验收 | 已证明 |

## 6. 验证记录

```text
uv run ruff check src tests
  => passed
uv run pyright
  => 0 errors
uv run pytest -q <memory/api/MCP/runtime/policy targets>
  => 53 passed
HARNESS_TEST_DATABASE_URL=...:55432/harness uv run pytest -q \
  tests/integration/storage/test_memory_bank_postgres.py \
  tests/integration/storage/test_data_lifecycle.py
  => 6 passed
alembic upgrade head -> downgrade 0014 -> upgrade head
  => PostgreSQL 17.5 真实容器通过
npm test
  => 35 files, 153 passed
npm run build
  => passed，包含 /settings/memory 和 /api/memory-bank/[...path]
```

全仓 `pytest -q` 在未注入默认 `localhost:5432/6379/9000` 基础设施时结果为 584 passed、
4 skipped，剩余均为连接错误。它不作为通过证据；G18 最终验收会用真实 PostgreSQL、Redis、
MinIO 和明确端口映射重跑完整套件。

## 7. 后续边界

- 当前检索是关键词 Adapter，不宣称向量语义召回；引入向量库时必须保持相同 scope 与删除
  一致性测试。
- Memory Bank 存稳定偏好和经确认事实，不存原始完整聊天，也不替代业务主数据系统。
- 跨 Agent 共享默认关闭；未来若增加共享，必须成为显式授权资源，不能放宽现有查询条件。
- 远端写入依赖 Sandbox 可达的 HTTPS URL；留空时远端只读取现有投影，不获得写工具。
