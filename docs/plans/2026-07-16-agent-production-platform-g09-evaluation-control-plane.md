# G09 持久化 Eval 控制面完成报告

## 结论

G09 已把原有 CLI `EvalRunner` 扩展为可排队、可恢复、可取消、可下载报告并能阻断晋级的
耐久 Eval 控制面。评分仍复用既有 Run/Event 确定性规则；Studio 或浏览器不能提交“通过”
结论。每个 Case 使用独立 Session 和稳定 Run 幂等键，一个 Case 的基础设施失败不会终止整套。

## 数据模型与持久化

Migration `0009` 新增三张租户隔离表：

- `eval_dataset_versions`：不可变 Dataset Version，固定 Draft revision、content/package hash、
  Case 定义和输入 Fixture 证明；
- `eval_runs`：目标 Agent/Version、可选 Preview/Environment 关联、活动 Case、fencing token、
  状态和报告元数据；
- `eval_case_results`：Session/Run、终态、断言失败、工具、审批和耗时证据。

PostgreSQL Repository 使用 payload envelope 校验与 status/fencing CAS；Redis 使用独立
`harness:eval` namespace 和 visibility lease。非终态 reconcile 原子 reschedule 当前租约，只有
终态才 ACK，避免 ACK 与重新入队之间的崩溃窗口。Dataset 输入 Fixture 与 JSON/JUnit 输出使用已有
MinIO/S3 `ArtifactStore`，下载接口再次校验租户和 Eval Run 归属。

## 执行状态机

Eval Controller 采用短步 reconcile，而不是在 Worker maintenance 中等待子 Run：

1. 固定 Dataset/Agent Version 并进入 `running`；
2. 为当前 Case 创建确定性 Session ID；
3. 上传固定 Fixture，使用稳定幂等键创建普通 Run；
4. 让主 Run Worker 正常执行；
5. 后续 reconcile 从 Run/Event 读取证据并评分；
6. 持久化 CaseResult、推进下一 Case；
7. 全部完成后生成 `report.json`、`junit.xml`，收敛为 `passed` 或 `failed`。

Preview/Approval 维护、Eval reconcile 和主 Run Worker 分属独立异步循环，因此长 Run 不会阻塞
Eval 超时检查。Case 超时会取消服务端 Run；预期的 `waiting_approval` 可作为可评分观察点，评分
完成后同样取消该非终态 Run。取消整套 Eval 会先取消活动 Run，写入部分报告，再进入
`cancelled`。

## 确定性评分与晋级门禁

每个 Case 继续断言：

- Run 终态；
- required/forbidden tools；
- 是否请求审批；
- 输出包含文本；
- 最大时长。

`EvalControlPlaneService.require_promotion_allowed()` 和 evaluation-gate API 只接受目标 Agent
Version 已通过每个最新 required Dataset Version 的情况。G10 的 Deployment/Promotion 控制器
可以直接消费该门禁，不需要从 UI 推断状态。

## API 与 Studio

新增 API：

- Dataset Version：create/list/get；
- Eval Run：create/list/get/cancel；
- JSON/JUnit Artifact 下载；
- Agent Version evaluation gate。

Studio “测试与发布”页现在支持固化 Dataset、新建 Dataset 版本、运行固定版本 Eval、自动轮询、
取消、逐 Case 失败证据、报告下载和最近版本对比。页面同时展示真实 Preflight 与 required
Dataset 门禁，移除了“离线评测待接入”等过期占位文案。

## 验收证据

- `make verify`：Ruff、Pyright、3 个 Agent package 检查通过；`511 passed, 2 skipped`。
- Web：`142 passed`，Next.js production build 通过。
- Migration 从空库升级至 `0009 (head)`。
- PostgreSQL Engine 重建后 Dataset、EvalRun、CaseResult 与 fencing 状态保持一致。
- Redis Eval Controller 租约在 owner 崩溃后可重新获取。
- 测试覆盖 Case 基础设施失败继续、超时取消、人工审批观察点、整套取消、Controller 重建续跑、
  稳定幂等、required Dataset 晋级阻断、自动本地双队列执行和报告下载。
- 浏览器验收确认评测控制卡、三个 Case、门禁状态和空态可读，控制台无 warning/error；动作按钮
  已改为独立行并禁止文本换行，避免三栏布局中的挤压。
- `git diff --check` 与变更文件 Secret 扫描通过。

两个 skip 是需要外部配置的 Tavily live 与真实 Preflight opt-in 测试，与 G09 本地确定性覆盖
无关。
