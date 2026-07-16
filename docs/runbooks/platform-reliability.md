# Agent Harness 平台可靠性 Runbook

## 1. 适用范围

本 Runbook 面向 API、Worker、PostgreSQL、Redis、对象存储、Sandbox 与 Langfuse
链路。当前阶段不提供运营管理页面；值班入口是 Prometheus 告警、`/metrics`、持久化
`reliability_incidents` / `reaper_actions`，以及应用日志。

API 指标由 `api:8000/metrics` 暴露，Worker 与 Reaper 指标由
`worker:8001/metrics` 暴露。指标不携带 tenant、user、run、session 或 URL 等高基数
标签。API scrape 必须使用 `HARNESS_API_BEARER_TOKEN`；Worker 端口只允许监控网络访问，
不得通过宿主机或公网发布。

## 2. 服务目标

| 目标 | 阈值 | 数据源 |
| --- | ---: | --- |
| Run 创建 P95 | `< 500ms` | API middleware |
| durable event 首次读取 P95 | `< 2s` | observed event repository |
| 取消 API P95 | `< 10s` | API middleware |
| 审批恢复 API P95 | `< 10s` | API middleware |
| Artifact 下载成功率 | `> 99.9%` | artifact API |
| 终态 Trace 完整率 | `> 99%` | terminal quality hook |

进程重启会清空进程内 Summary 样本，因此告警使用窗口并允许 `no data`，不把进程刚启动
误报为健康或故障。长期趋势由 Prometheus 保存。

## 3. 状态阈值与自动回收

| Run 状态 | 默认阈值 | 自动终态 |
| --- | ---: | --- |
| `queued` | 120s | `timed_out` |
| `provisioning` | 300s | `timed_out` |
| `running` | 3600s | `timed_out` |
| `waiting_approval` | 900s | `timed_out` |
| `cancelling` | 30s | `cancelled` |

Reaper 每 30 秒运行一次。它先重新读取 Run，再以 `status + fencing_token` 做 CAS；Run
已经推进或刚刷新过 `updated_at` 时只记录 `skipped`，不会误杀。终态事件、Quota 释放、
Credential Lease 撤销任一步失败，都会生成 `reaper_finalize_failed` 事故。下一轮由带 30 秒
租约的单 Worker 抢占修复，避免多 Worker 同时补偿；租约到期后可由其他 Worker 接管。

## 4. 容量模型

首个需要扩容的信号是 Redis ready queue，而不是 CPU 单点。建议同时观察：

- `harness_queue_tasks{state="ready"}`：持续增长表示到达率超过完成率；
- `harness_queue_tasks{state="processing"}`：接近 Worker 并发上限时是已用执行槽；
- Run 五类活动状态：判断拥塞发生在排队、环境准备、模型执行、审批还是取消；
- active Preview、Sandbox、Approval 与 Credential Lease：判断外部资源占用；
- PostgreSQL pool checked-out：判断是否先受数据库连接池限制；
- Artifact/Snapshot bytes 与 Lifecycle backlog：判断存储和清理速度。

初始硬告警为 ready queue `>= 1000` 持续 10 分钟。正式生产前应以压测得到的单 Worker
安全吞吐 `R` 和目标等待时间 `W` 调整：`ready_queue_budget = worker_count × R × W`。
不要只提高队列阈值；必须同时验证数据库连接、Sandbox 配额和模型网关限流。

## 5. 告警处置

### Run 创建延迟

1. 对比 API 实例的 P95，确认是单实例还是全部实例；
2. 检查 PostgreSQL 连接池、Run 唯一约束等待和 Redis enqueue 延迟；
3. 若数据库已饱和，先限制新流量，再扩容连接池/实例；禁止绕过持久化直接返回成功。

### Event 可见延迟

1. 检查 PostgreSQL `run_events` 写入与 Redis EventBus；
2. EventBus 失败时客户端仍应能从 PostgreSQL 回放，不得丢失 durable event；
3. 恢复后确认 sequence 连续，并观察告警窗口自然恢复。

### Artifact 下载失败

1. 区分 401/403/404 与 MinIO 5xx/超时；
2. 检查 Artifact 元数据是否为 `ready`、对象 key 是否存在、sha256 是否一致；
3. 禁止用空文件或元数据成功代替对象存储失败。

### Trace 不完整

1. 检查终态 Run 是否有 `traceparent` 和 durable events；
2. 检查 quality queue 与 Langfuse exporter；
3. Langfuse 故障不能改变 Run 终态。保留 retryable quality record，恢复后重放。

### 卡死 Run

1. 查询 `reaper_actions` 的 expected/observed/outcome；
2. 查询相同 run 的 `reaper-finalize:<run_id>` 事故和 recovery attempts；
3. 若 CAS 一直 skipped，说明 Run 正在推进，不做人工终止；
4. 若 finalize 一直失败，先恢复事件库、Quota 或凭证后端，再等待租约重试。

### Reaper 失败

维护 Reaper 相互隔离。一个 Preview/Sandbox/Lifecycle Reaper 失败不会阻止其他 Reaper。
根据 `reaper` 标签定位后端；修复后下一轮成功会自动 resolve 对应 fingerprint。

### 队列积压

1. 对比 ready 与 processing；ready 增长而 processing 为零通常是 Worker 不可用；
2. 检查 Redis、Worker 健康、任务 visibility lease 和执行后端；
3. Worker 扩容前检查模型网关、Sandbox、PostgreSQL 和租户 Quota；
4. Redis 恢复后过期 processing task 会重新可见，Run fencing 阻止陈旧执行者覆盖新状态。

## 6. 故障演练矩阵

| 注入 | 期望证据 | 不允许发生 |
| --- | --- | --- |
| Worker 在 dequeue 后退出 | visibility 到期后重新投递；旧 fencing 失败 | 两个执行者同时提交终态 |
| Redis 暂时不可用 | Worker 记录续租失败；Run 仍以 DB CAS 收敛 | 返回伪成功或丢 durable event |
| PostgreSQL 写失败 | API/Worker 明确失败并重试 | 只写 Redis 后宣称成功 |
| Sandbox 创建/销毁失败 | Run/incident 留下错误；Reaper 重试 | 自动回退到 unsafe local |
| Langfuse 不可用 | quality record 可重放；Run 终态不变 | 因观测后端失败回滚业务结果 |
| Reaper finalize 中断 | open incident + recovery lease + 单一补偿 | 重复终态事件或永久泄漏配额 |

演练后必须确认：Run 终态唯一、事件 sequence 连续、Quota/Credential 无泄漏、事故能自动
resolve、Artifact 可下载、Trace 最终补齐。演练环境不得使用生产凭证。
