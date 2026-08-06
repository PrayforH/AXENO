# G15 租户配额、成本与资源准入验收记录

## 结论

Harness 已建立 tenant / agent / environment 三级 QuotaPolicy、原子 ResourceReservation 与
UsageLedger。Run、Sub Agent、MCP、Artifact、Workspace Snapshot、Preview 和 Deployment 晋级
均在创建副作用前执行确定性准入；API 与 Worker 分别校验，超限返回稳定错误并最终释放遗留预留。

## 已完成范围

- 新增 QuotaPolicy、QuotaCounter、ResourceReservation、UsageLedger 模型、PostgreSQL Repository
  与 `0012` migration；内存和 PostgreSQL 实现共享相同的 reserve / commit / release 协议；
- 支持租户、Agent、环境及 Agent + 环境组合约束，未覆盖的资源继续使用平台默认值；计数窗口按
  活动资源、MCP 分钟和累计资源月份区分；
- Run API 在写入 Run 前预留并发、模型 Token 和成本预算；Worker 在创建 Sandbox 前再次确认
  admission，直接投递或 API 崩溃恢复路径不能绕过配额；
- Run 成功、失败、取消、超时和过期均释放并发与 Sub Agent 预留；Worker 维护循环回收过期
  reservation；配额异常形成 `quota_exceeded` API code 或 `quota_exceeded_<resource>` Run error；
- MCP 调用按秒执行 QPS 准入，Task / Agent 委派占用 Sub Agent 并发；Artifact 与 Snapshot 按实际字节
  预留并提交；Preview 按活动实例计数；Deployment 晋级按月计数；
- 模型结果按 input、output 和 cache token 汇总，成本缺失写入 `unknown` ledger，绝不折算为 0；
- 新增 `/v1/studio/quotas` 查询和 revision CAS 修改接口；owner/admin 可修改并写审计，member/
  viewer 只能查看；
- Agent Studio 增加“用量”页，以容量账本展示 committed、reserved、limit、未知成本和活动
  reservation；Agent 运行设置增加单次模型 Token 上限；
- 页面沿用 Studio 的安静控制面视觉体系，在桌面、窄屏和键盘焦点下保持可用，不引入独立后台
  设计语言。

## 验收证据

- 后端全量：574 passed、4 skipped、5 个既有依赖弃用 warning；Ruff 与 Pyright 通过；
- PostgreSQL 真并发争抢：8 个请求争抢 2 个名额，仅 2 个成功、6 个稳定拒绝，重建 Service 后
  counter 与 reservation 仍可恢复；
- API 集成证明 Run 与 Preview 超限不创建半成品，排队 Run 取消后名额立即可复用；Worker 未经
  API 准入时在 Sandbox provision 前失败并收敛到 terminal；
- 单元与集成覆盖 MCP、Sub Agent、Artifact、Snapshot、Deployment、层级聚合、幂等部分提交、
  取消/过期释放、成本 unknown 和策略 revision 冲突；
- 权限集成证明 member/viewer 修改返回 403，owner 修改后产生 `quota.policy.replace` 审计记录；
- 前端 147 tests passed，Next.js production build passed；
- 浏览器实际验证 `/studio/usage` 的登录、默认用量、9 类资源、活动 reservation、策略 r0 → r1
  保存闭环；同时发现并修复字节输入步长导致默认 5GB/20GB 无法提交的问题。

## 运行语义与边界

- `reserved` 是尚未结算的最坏情况占用，`committed` 是实际可确认用量；活动并发资源在终态释放，
  不作为累计消费提交；
- 平台默认策略是 revision 0 的合成基线，首次管理修改生成 revision 1；部分策略未声明的资源不会
  失去默认保护；
- 当前成本单位为 micro-USD，页面转换为 USD；网关未返回成本时必须保留 unknown，运维应检查
  模型路由的 usage/cost 映射；
- Reservation Reaper 提供最终一致释放，但生产仍应对长期 active reservation、unknown cost 和
  高频 quota rejection 建立告警；
- 当前管理页编辑租户默认策略；Agent / environment 细粒度策略已由 API 与数据模型支持，可在后续
  Studio 迭代增加作用域筛选和专用编辑器。
