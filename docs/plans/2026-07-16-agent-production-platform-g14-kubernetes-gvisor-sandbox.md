# G14 Kubernetes + gVisor 生产执行后端验收记录

## 结论

Harness 已增加符合现有 Sandbox Contract 的 Kubernetes/gVisor per-run 执行后端。
Worker 使用受限 RBAC 创建一个 Run Pod 和一条先于 Pod 生效的默认拒绝 NetworkPolicy；
沙箱内执行文件、Bash 与 Claude CLI，运行结束由正常清理或 TTL Reaper 最终回收。任何
Kubernetes、RuntimeClass、网络或 CLI 失败都会形成显式运行/预检失败，不会回退 Local。

## 已完成范围

- 新增 `KubernetesSandboxProvider` 与 `KubectlKubernetesClient`，保持 provision、prepare、
  execute、collect、destroy 五段 Sandbox Contract；
- 每 Run 使用独立 Pod、工作区 `emptyDir` 和 `/tmp` 临时写层；基础镜像只读并按 digest 固定；
- Pod 固定 gVisor RuntimeClass、非 root UID/GID、RuntimeDefault seccomp、drop ALL capabilities、
  禁止 privilege escalation、privileged、hostNetwork、hostPath 和 ServiceAccount Token；
- Claude CLI 预装固定版本，prepare 时再次核验；模型与 MCP 短期凭据只经 exec stdin frame
  注入，不进入 PodSpec、kubectl argv 或环境配置资产；
- NetworkPolicy 在 Pod 之前创建，拒绝全部入站，只允许 kube-dns 和指定端口的平台代理；
  Squid egress proxy 再按域名 allowlist 拒绝未注册域名和直接 IP；
- 输入工作区以 tar 流同步，输出归档逐成员校验路径、类型、成员数与总大小；拒绝 traversal、
  symlink、特殊文件和超限归档，kubectl 下载流也有提前终止上限；
- Worker 的 Artifact 自动收集由 Daytona 特例提升为所有 `CONTAINER` 级远程 Sandbox 共享；
- 取消、超时、失败和成功继续走统一 destroy；创建中途失败会删除部分资源；独立维护循环按
  不可变到期注解回收 Worker 崩溃遗留 Pod 与 NetworkPolicy；
- 新增 `gvisor-production@v1` Execution Profile；生产 Preflight 和 Deployment Session 校验
  Profile 固定 Provider 与实际 Worker Provider 一致，不允许静默错配；
- 提供 sandbox 镜像、Helm RuntimeClass/Namespace/SA/RBAC/egress proxy 资产、Docker Compose
  配置入口和真实集群 opt-in E2E。

## 验收证据

- 后端全量：554 passed、4 skipped；Ruff、Pyright、Agent 包门禁和所有基础设施集成测试通过；
- 前端：144 tests passed，Next.js production build passed；
- Sandbox 镜像在本机实际构建成功，以 UID/GID 1000 运行，`claude --version` 精确返回
  `2.1.206 (Claude Code)`；
- Fake 集群测试验证 Pod/NetworkPolicy 安全字段、网络资源创建顺序、输入/输出同步、CLI 检查、
  创建失败清理、过期回收、归档 traversal/symlink/大小拒绝和无 Local 回退；
- exec framing 测试证明模型 Token 和私有 System Prompt 不出现在 kubectl argv 或明文 stdin；
- Preflight 失败注入证明固定 Daytona Profile 不能在 Local/gVisor 以外后端悄悄运行；
- 既有 RunOrchestrator 回归覆盖审批暂停、恢复、Artifact、取消、超时、Trace 与 destroy，现已
  通过统一 Container Sandbox 路径复用；
- Docker Compose 配置渲染通过；真实集群用例因当前机器无 Kubernetes/gVisor 集群而按设计
  skipped，设置 `HARNESS_KUBERNETES_E2E=true` 后会验证 Pod、CLI、Bash 和未允许 IP 出网失败。

## 运维边界

- 集群必须先安装 gVisor `runsc` handler；Chart 不会伪装缺失的 RuntimeClass；
- sandbox 镜像必须推送并以 registry digest 配置，tag 或空值启动即失败；
- 生产必须配置已注册 egress proxy，空 selector/URL 启动即失败；域名 allowlist 需和 MCP/模型
  Registration 的实际目标同步变更；
- 当前一个 Worker 进程绑定一种实际 Sandbox Provider。不同 Profile 应使用独立 Worker Pool 和
  队列路由；若 Deployment Profile 与 Worker Pool 不匹配，Run 会 fail closed。
