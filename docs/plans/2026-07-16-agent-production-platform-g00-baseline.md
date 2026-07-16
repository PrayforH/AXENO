# G00 可复核执行基线

- **Goal：** G00 建立可复核执行基线
- **日期：** 2026-07-16
- **分支：** `feature/agent-studio-control-plane`
- **基线父提交：** `ac1298d feat: add production-grade multi-agent studio`
- **结论：** G00 文档、自动化和部署健康门禁通过；外部黑盒运行存在已记录的后续缺口

## 1. G00 范围

G00 不实现 Studio API、Draft PostgreSQL 或新的运行能力。它负责冻结当前真实状态，让
G01～G19 可以从同一可复核基线继续：

- 提交总体方案和 Goals/Loops；
- 建立设计到 Goal 的覆盖关系；
- 记录分支、migration、测试和部署状态；
- 运行本地、容器和外部 smoke；
- 明确通过、跳过、失败和后续归属；
- 保证工作树不包含 Secret 或未知生成物。

## 2. 要求与证据矩阵

| 要求 | 权威证据 | 结论 |
| --- | --- | --- |
| 总体方案 | `docs/agent-production-platform-design.md` | 已证明 |
| Goal/Loop 拆分 | `docs/plans/2026-07-16-agent-production-platform-goals-and-loops.md` | 已证明 |
| 设计范围覆盖 | Goals/Loops 第 10 章，G00～G19 引用和依赖自动检查 | 已证明 |
| 当前分支包含最新 develop | `git rev-list --left-right --count HEAD...origin/develop` 为 `6 0`；`origin/develop` 是 HEAD 祖先 | 已证明 |
| 单一 migration head | 代码和运行数据库均为 `0005 (head)` | 已证明 |
| Python 质量门禁 | Ruff、Pyright、Agent check、Pytest | 已证明 |
| Web 质量门禁 | 30 个测试文件、130 个测试、Next.js production build | 已证明 |
| Agent 可复现打包 | 3 个参考 Agent 均 READY 并输出 runtime/package hash | 已证明 |
| Docker 配置和健康 | Compose config、API/Web/Worker/PostgreSQL/Redis/MinIO health | 已证明 |
| 外部模型网关 | Anthropic-compatible new-api SDK smoke | 已证明 |
| Daytona 连通性 | 创建临时 Sandbox 并访问模型网关 origin | 已证明 |
| Docker 完整业务 E2E | 真实 Run 进入审批，批准后因 `error_max_turns` 失败 | 未通过，已分配 G08/G13/G17/G18 |
| Tavily Live Test | 缺少显式 `HARNESS_RUN_LIVE_TESTS=1`，测试按契约跳过 | 跳过，不计通过 |
| 工作树 Secret | 变更文件敏感字面量扫描为空 | 已证明 |
| 临时测试容器 | `harness-g00-*` 容器和网络已删除 | 已证明 |

## 3. Git 与合并基线

执行时状态：

```text
branch: feature/agent-studio-control-plane
HEAD before G00: ac1298d
origin/develop: 9dffe63
HEAD...origin/develop: 6 ahead, 0 behind
origin/develop is an ancestor of HEAD: yes
```

现有其他 worktree 属于独立历史任务，G00 未修改：

- `feature/phase-1`；
- `feature/production-agent-scaffold`；
- `feature/web-console-enhancement`；
- `main` worktree。

### 后续合并策略

1. G00 在当前集成分支形成一个文档/基线提交；
2. G01 和 G02 从 G00 提交分别创建 worktree；
3. G01 不新增 migration；
4. G02 独占下一 migration `0006`；
5. G01/G02 通过各自审计后合并回当前集成分支；
6. G03 只在两者合并后开始，并独占主应用 composition root；
7. 后续按照 Goals/Loops 的波次执行，不并行修改同一 migration 或 composition root。

## 4. Migration 基线

代码 migration 链：

```text
0001 -> 0002 -> 0003 -> 0004 -> 0005 (head)
```

运行中 PostgreSQL 容器：

```text
alembic current: 0005 (head)
alembic heads:   0005 (head)
```

宿主机直接执行 `alembic current` 默认访问 `localhost:5432` 会失败，因为当前 Compose 把
PostgreSQL 映射到 `15432`。这不是 migration 漂移；容器内连接已经证明数据库处于 head。
后续需要宿主机运行数据库命令时，应使用显式测试服务或正确的映射连接，不能把默认端口
失败误判为 Schema 失败。

## 5. 自动化验证

### 5.1 Python

首次在没有默认端口测试基础设施时：

```text
403 collected
394 passed
1 skipped
5 failed
3 errors
```

8 个未通过项全部固定连接：

- PostgreSQL `localhost:5432`；
- Redis `localhost:6379`；
- MinIO `localhost:9000`。

当前生产 Compose 使用 `15432 / 16379 / 19000`，因此 G00 临时启动了只用于测试的默认
端口 PostgreSQL、Redis 和 MinIO，使用测试约定凭据和 Bucket，随后重新执行
`make verify`：

```text
Ruff:    passed
Pyright: 0 errors, 0 warnings
Pytest:  402 passed, 1 skipped, 5 warnings
```

唯一跳过项：

```text
tests/integration/runtime/test_tavily_mcp_live.py
reason: set HARNESS_RUN_LIVE_TESTS=1 to run external model smoke tests
```

### 5.2 Web

```text
Vitest files: 30 passed
Vitest tests: 130 passed
Next.js build: passed
Studio route: static page generated
```

### 5.3 Agent Package

```text
echo-agent@0.4.0
runtime: 67bf32ed72b7b724edf7ce1ef4ccb1c3d64b1554632578fa81c000b038faca09
package: 3ca930a5cbc7e441f10592e2055980888a243605a2933179c5523dde6ef3d104

helper-agent@1.0.0
runtime: b8d23687771456428dc5d967a5befa373f7b2ca8fbeb4bf8904086ee9fb4e6f1
package: ff5e74243bc8487c241afbb3b94876a03e5780a7d2d23cc29659cf30faac9c19

public-opinion-agent@0.1.1
runtime: 7a43b696a0791c20cb66516ad36e16041349a363c5d444dcd056860b9f4040fd
package: c2502d0104dffc854c04db1431807a1e3c67e4e9be34683cbb8ce52c4a338e96
```

三个 Package 均包含 3 个 Eval Case，并通过生产检查和确定性打包。

## 6. Docker 与外部依赖

### 6.1 当前健康状态

```text
api=healthy
worker=healthy
web=healthy
postgres=healthy
redis=healthy
minio=healthy
GET /healthz = 200
GET / = 200
GET /studio/agents = 200
```

OTel Collector 正在运行，但不参与 Compose health gate。

### 6.2 当前真实执行配置

只记录非敏感事实：

```text
HARNESS_ENVIRONMENT=production
HARNESS_RUNTIME=claude-sdk
HARNESS_SANDBOX_PROVIDER=local
HARNESS_ALLOW_UNSAFE_LOCAL_SANDBOX=true
HARNESS_OTEL_ENABLED=true
model=deepseek-v4-pro
```

这与总体方案中“生产环境使用 Daytona 或 gVisor，禁止 unsafe local”的目标存在明确差距。
G00 仅记录事实，不在基线提交中静默切换运行后端。

### 6.3 Daytona smoke

结果：

```text
PASS: created a disposable Daytona sandbox
PASS: sandbox reached the configured model gateway origin
```

访问 origin 返回 HTTP 401，说明网络可达且未携带业务凭据；该 smoke 不验证完整模型请求。

### 6.4 Anthropic-compatible 模型 smoke

真实 Claude Agent SDK smoke 通过，事件包含：

- Read tool request/result；
- Task tool request/result；
- Sub Agent started/completed；
- streaming message delta；
- runtime result。

### 6.5 Docker 黑盒 E2E

测试目标是输入文件、Workspace 输出、Artifact、Session Workspace 恢复和服务重启。

实际结果：

1. Agent 正确读取输入文件；
2. 模型尝试 Bash 搜索文件，Policy 正确创建审批并进入 `waiting_approval`；
3. 人工通过真实 Approval API 批准 Bash；
4. Agent 尝试 Write，Policy 再次正确进入审批；
5. 人工批准 Write；
6. Write 和 Read 成功；
7. Run 在第 6 轮以 `error_max_turns` / `runtime_result_error` 失败；
8. 因首轮未成功，Artifact、第二轮 Workspace 恢复和服务重启断言没有执行。

该失败证明审批和状态机生效，但不能证明完整 Docker E2E。后续归属：

| 缺口 | Goal |
| --- | --- |
| Preview 中真实模型/Sandbox/MCP/审批预检 | G08 |
| Production 仍允许 unsafe local | G13 |
| 卡住/失败状态、E2E 可操作性和故障演练 | G17 |
| 最终 Docker/Kubernetes 端到端发布门禁 | G18 |

## 7. 安全与清理

- 未把任何 `.env`、Token、API Key、Daytona Key 或 Langfuse Key 写入仓库；
- 验证命令只从本地未提交 env 文件注入 Secret；
- 文档只记录非敏感配置事实；
- `harness-g00-postgres`、`harness-g00-redis`、`harness-g00-minio` 和临时网络已删除；
- Agent 打包输出未出现在 Git 工作树；
- 其他 worktree 和用户容器未修改。

## 8. G00 完成审计

### 自动化

- Targeted tests：文档链接、Goal 编号、依赖图、Secret scan；
- Adjacent regression：Studio、auth、runtime、storage tests 包含在全量 Pytest；
- Full relevant suite：402 passed，1 个显式 live skip；
- Web：130 passed，production build passed；
- Agent：3 个参考 Package check/pack passed。

### 真实运行

- API/Docker health：通过；
- Daytona 网络 smoke：通过；
- Anthropic-compatible SDK smoke：通过；
- 完整 Docker E2E：未通过，失败已直接记录并分配后续 Goal；
- Browser：G00 复用已部署 `/studio/agents` 的 200 健康事实，UI 真实交互属于 G05 及后续。

### G00 结论

G00 的目标是建立真实基线，而不是让所有后续能力提前通过。所有 G00 要求均有直接证据，
未通过的完整 Docker E2E 没有被隐藏或降级，且已经进入明确后续 Goal。G00 完成后可以按
依赖并行启动 G01 和 G02。
