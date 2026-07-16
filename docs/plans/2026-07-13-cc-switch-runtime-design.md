# cc-switch Claude Runtime 本地接入设计

## 目标

本地启动 Harness 时，可显式选择 Claude Agent SDK Runtime，并复用 cc-switch 已应用到 `~/.claude/settings.json` 的当前 Claude Provider。切换 cc-switch Provider 后，重启 Harness 即可生效；默认测试与无配置启动仍使用 Fake Runtime。

## 方案选择

采用启动脚本读取 cc-switch 的已应用配置，而不是读取 `cc-switch.db` 或依赖其本地代理：

- `~/.claude/settings.json` 是 Claude Code 当前实际使用的配置，接口比 cc-switch 内部数据库稳定。
- cc-switch 本地代理当前未启用，直接复用 Anthropic-compatible endpoint 可减少一层运行依赖。
- Token 只存在于父进程和 API 子进程环境，不写入仓库 `.env`、命令行参数、日志或事件。

## 架构与数据流

1. 新增本地启动配置加载器，解析 `~/.claude/settings.json` 中允许的字段：`ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_API_KEY` 和模型别名。
2. 启动脚本在 `HARNESS_RUNTIME=claude-sdk` 时加载这些值，并映射为 Harness 配置；Fake Runtime 启动不读取用户凭据。
3. API 组合根根据 `Settings.runtime` 选择 Runtime：
   - `fake`：保持现有 `FakeRuntime`。
   - `claude-sdk`：使用动态代理 Runtime。每次 Run 根据 Session 从 Agent Registry 读取已发布的 `AgentVersion`，创建 `ClaudeSdkRuntime`。
4. 本地默认 Agent 的模型 route 使用 cc-switch 当前模型，并将必需能力限制为本次可验证的 streaming；工具能力通过后续显式 smoke 再扩大声明。
5. Claude SDK 事件继续进入现有 Harness Event → AG-UI → CopilotKit 链路，WebUI 无需知道网关或密钥。

## 错误与安全边界

- 配置文件缺失、JSON 非法、endpoint/model/token 缺失时启动失败，给出不含密钥的明确错误。
- 选择 `claude-sdk` 后绝不静默退回 Fake Runtime。
- 不输出配置原文，不把 token 放入 Pydantic repr、事件、Trace 属性或 Git 文件。
- cc-switch 切换不会热更新运行中的 API；重启后读取新配置，避免进行中的 Run 被中途换路由。

## 测试与验收

- 单元测试：配置白名单、缺失字段、敏感值不出现在错误信息中。
- 组合根测试：`fake` 与 `claude-sdk` 选择正确；动态 Runtime 从 Session 解析 AgentVersion。
- SDK fake transport 测试：endpoint、模型和认证环境映射正确。
- 启动冒烟：使用当前 cc-switch Provider 完成一次真实 SDK 请求。
- Web 验收：页面发送不含 Fake 标记的普通问题，收到真实模型回答；API/Web 保持 200，浏览器无新增运行错误。
