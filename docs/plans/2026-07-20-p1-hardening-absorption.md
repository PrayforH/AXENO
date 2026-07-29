# P1 Existing Function Hardening 吸收决策

日期：2026-07-20
参考分支：`auto/p1-existing-function-hardening`
当前基线：`develop`

## 结论

参考分支包含运行可靠性、版本治理、评测证据、内部知识与数据访问及旧版 Studio
控制面等多组改动。它与当前基线已经明显分叉，且双方的 Alembic `0016` 至
`0019` 已用于不同功能，因此不整支合并，也不直接连续 cherry-pick。

后续按能力手工移植，并以当前数据模型、Codex 主题和 Agent Studio 交互为准。

## 可吸收能力

| 优先级 | 能力 | 参考提交 | 决策 |
| --- | --- | --- | --- |
| P0 | Worker 队列故障隔离 | `a163cfd` | 已实施（2026-07-27） |
| P0 | 真实取消与 durable terminal | `783bba8` | 本批实施 |
| P0 | Queue/首事件/首正文分段延迟 | `8c81e38` | 已实施（2026-07-27） |
| P1 | 多租户公平 Run Queue | `c429b66` | 待实施 |
| P1 | Agent 版本运行影响 | `2ce92f0` | 待实施 |
| P1 | Agent 版本生命周期治理 | `44405db` | 待实施 |
| P2 | Evaluation Gate 发布证据 | `377567a` | 评测系统稳定后实施 |
| P2 | Capability Truth CI | `scripts/check_capability_truth.py` | 待实施 |

旧版 Studio 页面、整套旧 CSS、内部向量知识库与 Data Access 子系统不直接吸收。
外部知识库继续通过 MCP/外部服务接入，但保留固定版本坐标、服务端身份、引用、
不可信内容标记和 fail-closed 等安全原则。

## 当前实施范围：真实取消

取消状态的所有权调整为：

1. API 接到停止请求后，只把 `provisioning` 或 `running` 推进为 `cancelling`；
2. API 不提前写入 `run.cancelled`，也不提前释放仍由 Worker 持有的运行资源；
3. Worker 观察 durable `cancelling`，中断 Runtime stream；
4. Worker 为已经启动的 Sub Agent 写入终态；
5. Worker 持久化 `run.cancelled`，随后由 finalizer 清理 Sandbox；
6. Worker 失联时由 stuck-run Reaper 把超时的 `cancelling` 收敛到 `cancelled`；
7. `queued`、`waiting_approval` 等没有活动 Runtime owner 的状态仍可同步取消；
8. 重复停止请求保持幂等，返回当前 `cancelling` 或既有终态。

取消收敛指标从 HTTP 请求耗时改为“取消请求持久化到 durable `cancelled`”的真实耗时。

## P0.1 / P0.2 实施结果（2026-07-27）

- Worker 将 `dequeue`、`retry`、`acknowledge`、`extend_lease` 异常隔离在当前轮次或
  当前任务；队列后端抖动不再终止消费循环；
- 坏任务执行失败后排回队尾，不阻断其后的 Run；`retry` 或 `acknowledge` 失败时保留
  processing lease，由 visibility timeout 恢复，Run fencing 保证重复投递安全；
- 新增 `harness_worker_queue_failures_total{operation=...}`，只使用四个有界标签值；
- 新增 `harness_run_stage_duration_seconds{stage=...}`，采集 `queue_wait`、
  `runtime_first_event` 和 `runtime_first_text`；
- 审批指标改为从 durable `ApprovalRequest.created_at` 到成功 CAS 决策的真实等待时长；
- Reliability Overview 统一展示 Queue Wait、首 Runtime Event、首正文、审批等待和
  取消收敛 P95；恢复执行不会重复记录初始 Queue Wait，重复审批决定不会重复采样。

## 本批实施结果

- `RunService.cancel` 对活动 Run 只持久化 `cancelling`；
- Worker 中断 Runtime、收敛 Sub Agent 后持久化 `run.cancelled`；
- stuck-run Reaper 保留失联任务兜底并记录同一收敛指标；
- Reliability Overview 的取消 P95 改为 durable lifecycle，目标为 `<3s`；
- 定向覆盖 API、AG-UI、审批、Worker、Sub Agent、Reaper 和指标的 62 项测试通过；
- 仓库全量测试运行到 87% 时，非外部基础设施用例已通过 619 项；PostgreSQL、Redis、
  MinIO 未在本机监听导致对应 infrastructure 用例失败，因此中止该轮全量测试。

## 版本治理定义

版本治理不是删除旧版本，也不是简单切换下拉框。它管理不可变 Agent 版本从发布、
停止接收新流量到安全归档的完整生命周期，并在操作前展示和校验运行影响。

- **回退**：把环境路由从当前 Deployment Snapshot 指回旧 Snapshot；旧版本内容不变。
- **弃用**：旧版本不再接受新 Session 或新部署，但既有固定 Session 可以继续运行。
- **重新启用**：依赖仍然可用时，将弃用版本恢复为可部署状态。
- **归档**：仅在活动路由、固定 Session 和反向 Sub Agent 依赖全部清零后隐藏版本。
- **影响分析**：展示环境、流量权重、健康状态、部署结果和固定 Session 数。
- **审计**：记录原因、操作者、时间、前后状态和影响范围。

版本内容始终不可变。需要修改时从历史版本恢复为新 Draft，再发布新版本。
