# G17：SLO、Reaper 与故障恢复验收报告

日期：2026-07-16  
分支：`feature/platform-reliability-operations`

## 1. 结论

G17 已形成无运营页面依赖的可靠性底座：API 与 Worker 分进程暴露低基数 Prometheus
指标；五类活动 Run 都有可配置卡死阈值；Reaper 使用数据库 CAS/fencing 收敛终态；终态
事件、Quota 和 Credential Lease 清理失败后会生成持久化事故，并由 30 秒恢复租约保证单一
Worker 补偿。Preview、Approval、Quota、Workspace/Lifecycle、Credential 与 Sandbox Reaper
互相隔离，一个失败不会阻断其他清理任务。

按用户 2026-07-16 的最新决定，`/studio/operations` 页面和左侧“运营”入口本轮不建设，
已撤回试做代码。保留内部 `/v1/operations` 只读/管理员 API、Prometheus 指标、告警规则和
Runbook，后续需要页面时可以复用这些真实控制面事实。

## 2. 生产不变量

1. Run 只有 PostgreSQL 是权威状态；Redis 只承担可恢复投递。
2. 卡死检测先按索引筛选，再重新读取 Run，最后以 `status + fencing_token` 做 CAS。
3. `updated_at` 晚于 cutoff、状态已推进或 fencing 已变化时只记录 `skipped`，不误杀。
4. `queued/provisioning/running/waiting_approval` 收敛为 `timed_out`；`cancelling`
   收敛为 `cancelled`，且都经过领域状态机允许的转换。
5. CAS 成功但清理副作用失败时，不伪装成完整成功；生成
   `reaper_finalize_failed` incident，并保留失败 action。
6. 恢复租约落在 incident payload 中，PostgreSQL `SELECT FOR UPDATE` 保证并发 Worker
   只有一个抢占成功；租约到期后可接管。
7. 补偿前检查是否已有同类 reaper terminal event；Quota release 与 credential revoke
   均按幂等接口重试。
8. SLO reconciliation 只管理 `slo_breach/stuck_run/capacity_pressure`，不能错误关闭
   Reaper 或维护事故。
9. Capacity snapshot、incident 和 action 均保持 tenant 边界；平台维护事故只以
   `platform` 身份只读合并。
10. 指标标签使用 allowlist，不输出 tenant、user、run、session、URL 或资源 ID。

## 3. SLO 与指标

| SLO | 目标 | 指标 |
| --- | --- | --- |
| Run 创建 P95 | `< 500ms` | `harness_api_request_duration_seconds{operation="run.create"}` |
| Queue Wait P95 | `< 1s` | `harness_run_stage_duration_seconds{stage="queue_wait"}` |
| 首 Runtime Event P95 | `< 1.5s` | `harness_run_stage_duration_seconds{stage="runtime_first_event"}` |
| 首正文 P95 | `< 3s` | `harness_run_stage_duration_seconds{stage="runtime_first_text"}` |
| Event 首次增量读取 P95 | `< 2s` | `harness_event_visibility_delay_seconds` |
| 取消收敛 P95 | `< 3s` | `harness_workflow_convergence_seconds{workflow="run.cancel"}` |
| 审批等待 P95 | `< 10s` | `harness_workflow_convergence_seconds{workflow="approval.decide"}` |
| Artifact 下载成功率 | `> 99.9%` | `harness_artifact_download_total` |
| 终态 Trace 完整率 | `> 99%` | `harness_trace_terminal_total` |

> 2026-07-27 更新：取消与审批已从 API 请求耗时改为 durable lifecycle，
> 并补齐 Queue Wait、首 Runtime Event、首正文三段执行指标。

API 由 `/metrics` 暴露指标，生产环境需要 `HARNESS_API_BEARER_TOKEN`。Worker 在内部端口
`8001` 暴露 Reaper、Trace 和容量指标，Compose 只使用 `expose`，不发布到宿主机。

Event 可见延迟只统计 `after_sequence > 0` 的首次增量读取。历史页面第一次加载
`after_sequence=0` 不进入样本，避免把历史事件年龄误报为实时可见延迟。同一进程内同一
event ID 只记录一次。无 trace ID 的终态 Run 现在也会进入 `missing`，不会从分母消失。

Prometheus text exposition 遵循官方 0.0.4 格式约束：UTF-8、`HELP/TYPE`、末尾换行和
Counter/Gauge/Summary 类型。参考：[Prometheus exposition formats](https://prometheus.io/docs/instrumenting/exposition_formats/)。
HTTP 指标使用固定 operation 语义而不是原始路径，符合 OpenTelemetry 对稳定、低基数
HTTP 属性的方向。参考：[OpenTelemetry HTTP semantic conventions](https://opentelemetry.io/docs/specs/semconv/http/)、
[HTTP metrics](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/)。

## 4. 阈值与容量

默认状态阈值：

| 状态 | 秒 |
| --- | ---: |
| queued | 120 |
| provisioning | 300 |
| running | 3600 |
| waiting_approval | 900 |
| cancelling | 30 |

容量事实包括 Redis ready/processing、Run 状态分布、卡死状态、活动 Preview、等待审批、
Kubernetes Sandbox、数据库连接池、Artifact/Snapshot bytes、Lifecycle backlog 和活动凭证
租约。ready queue 初始硬告警为 `>= 1000` 持续 10 分钟；正式阈值应由压测吞吐
`worker_count × safe_rate × target_wait` 得到。

## 5. 持久化与 migration

`0014_platform_reliability_operations.py` 完成：

- 为 `runs` 增加独立、可索引的 `updated_at`；
- 新增 tenant-scoped `reliability_incidents`，包含 fingerprint 唯一约束、kind/status
  恢复索引和完整 payload；
- 新增 append-only `reaper_actions`；
- 新增 tenant-scoped `capacity_snapshots`；
- 验证 `0013 -> 0014 -> 0013 -> 0014`。

Incident upsert 使用 PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` 后锁定权威行，修复了
“两个事务同时看不到旧行”导致唯一约束竞争的问题。并发测试证明两个写入返回同一
incident ID，两个 recovery claimant 只有一个成功。

## 6. 故障演练证据

| 场景 | 验证结果 |
| --- | --- |
| 五种活动 Run 超时 | 5 个终态、5 个 action、fresh Run 不受影响 |
| finalize 中途失败 | open incident；下一轮租约修复；terminal event 不重复 |
| 两 Worker 同抢恢复 | 只有一个 lease winner |
| 一个 maintenance Reaper 失败 | 其他 Reaper 继续，失败 action/incident 可见 |
| Redis controller/worker lease 过期 | Preview/Eval/Deployment/Quality/Run 五组恢复测试通过 |
| Langfuse exporter 失败 | quality job retrying，Run 终态不变化 |
| Kubernetes ready 失败 | 清理资源并抛错，不回退 unsafe local |
| PostgreSQL incident 并发写 | 无唯一约束泄漏，fingerprint 保持单例 |
| tenant 同名 capacity snapshot | 两租户分别读取自己的快照 |

处置步骤见 [平台可靠性 Runbook](../runbooks/platform-reliability.md)，Prometheus 示例见
`deploy/prometheus/prometheus.example.yaml` 和 `deploy/prometheus/alerts.yaml`。

## 7. 验证记录

已执行：

```text
uv run ruff check src tests
uv run pyright
uv run pytest -q tests/unit tests/integration/api tests/integration/agui \
  tests/integration/test_approval_flow.py tests/integration/test_artifact_api.py \
  tests/integration/test_input_artifact_api.py tests/integration/test_workspace_lifecycle.py
  => 519 passed

uv run pytest -q tests/integration/storage/test_redis.py
  => 5 passed

HARNESS_TEST_DATABASE_URL=...:55432/harness uv run pytest -q \
  tests/integration/storage/test_reliability_postgres.py
  => 3 passed

HARNESS_TEST_REDIS_URL=...:56379/10 uv run pytest -q \
  tests/integration/storage/test_reliability_redis.py
  => 1 passed

alembic downgrade 0013 && alembic upgrade head
  => PostgreSQL 17.5 真实容器通过

docker compose -f deploy/docker-compose/compose.yaml config --quiet
ruby YAML parse deploy/prometheus/*.yaml
  => 通过
```

前端运营页面未交付、未计入通过项；这是明确的范围调整，不是遗漏。当前 Web 源码在撤回
后无 diff。

## 8. 后续边界

- 当前 Summary 样本保存在进程内，进程重启后由 Prometheus 长期时序承接；不把重启后的
  no-data 当作健康。
- 本轮只提供 Prometheus 配置示例，不在默认 Compose 中强制部署 Prometheus/Grafana。
- 若后续恢复运营页面，应读取持久化 incident/capacity/action 和 SLO API，不从日志或
  UI 文本反推状态。
