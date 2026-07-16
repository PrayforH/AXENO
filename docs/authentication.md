# 认证、单点登录与权限控制

Agent Harness 支持两种相互独立的登录方式：

- 使用邮箱和密码注册、登录；
- 使用 Google 或 GitHub OAuth 登录，OAuth 流程启用 PKCE 保护。

本地账号登录不依赖任何 OAuth 服务。Google 或 GitHub 的客户端配置为空时，
登录页面会自动隐藏对应的单点登录按钮。

## 本地验证

Docker 默认配置会开启邮箱注册，并关闭 Google、GitHub 单点登录。
访问 `http://localhost:3000/login`，注册第一个账号后即可登录。

在 `HARNESS_AUTH_DEFAULT_TENANT_ID` 指定的默认租户中：

- 第一个注册账号自动成为 `owner`；
- 后续自行注册的账号默认为 `member`。

因此，日常本地开发和自动化测试不需要连接 Google 或 GitHub，也不依赖外网。

### 在本地验证 Google/GitHub 登录

建议分别为本地开发和生产环境创建独立的 OAuth 应用。本地开发应用需要登记以下回调地址：

```text
http://localhost:3000/api/auth/oauth/google/callback
http://localhost:3000/api/auth/oauth/github/callback
```

然后配置：

```dotenv
AUTH_PUBLIC_URL=http://localhost:3000
AUTH_COOKIE_SECURE=false
AUTH_GOOGLE_CLIENT_ID=
AUTH_GOOGLE_CLIENT_SECRET=
AUTH_GITHUB_CLIENT_ID=
AUTH_GITHUB_CLIENT_SECRET=
```

访问站点时，浏览器地址必须与 `AUTH_PUBLIC_URL` 中配置的协议、域名和端口完全一致。
尤其不能混用 `localhost` 和 `127.0.0.1`：OAuth state 和 PKCE Cookie 按域名隔离，
回调过程中切换域名会导致登录校验失败。

OAuth 客户端密钥仅由 API 服务保存。Web 容器只接收公开的 Client ID，
浏览器端不会获得 Google 或 GitHub 的 Client Secret。

服务商配置参考：

- [Google OAuth 2.0 Web 应用接入说明](https://developers.google.com/identity/protocols/oauth2/web-server)
- [GitHub OAuth 应用授权说明](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)

## 登录会话安全

- 密码使用 Argon2id 计算哈希，API 不会返回密码或密码哈希；
- Access Token 使用 JWT，包含签发方、接收方、有效期、租户和角色等声明；
- Access Token 和 Refresh Token 由 Web BFF 写入 `HttpOnly`、`SameSite=Lax` Cookie；
- Refresh Token 以不可预测的随机值生成，数据库只保存其哈希；
- 每次刷新会轮换 Refresh Token；检测到旧令牌被重复使用时，会撤销整个令牌族；
- Google/GitHub OAuth 使用 state 校验和 PKCE，降低登录劫持与授权码窃取风险；
- API 从验签后的 Token 中读取 `tenant_id`、`user_id` 和角色，不信任浏览器自行提交的身份头；
- 生产环境不会接受普通请求伪造的 `X-Tenant-ID` 或 `X-User-ID`。

`HARNESS_API_BEARER_TOKEN` 是内部服务凭证，不是用户登录凭证。
Agent 配置同步等受信任任务通过 `X-Harness-Service-Token` 传递该凭证，
不得将它暴露给浏览器 JavaScript 或最终用户。

## 用户账户设置

登录后，用户可以从页面右上角的账户菜单进入“个人设置”或直接“退出登录”。

个人设置目前提供：

- 修改显示名称；
- 查看登录邮箱、工作区和当前角色；
- 本地密码账户修改密码；
- 查看当前浏览器会话并退出登录。

修改密码时必须提供当前密码。修改成功后，系统会撤销该用户的全部 Refresh Token，
并清除当前浏览器的登录 Cookie。其他设备已经签发的短期 Access Token 会继续存活到
自身有效期结束，但无法再刷新，之后必须使用新密码重新登录。

仅通过 Google/GitHub 创建、尚未设置本地密码的账号不能直接在设置页创建密码，
避免在缺少二次身份校验的情况下扩展登录方式。这类账号继续由对应的 OAuth 服务商
管理登录凭证。

## 角色与权限

| 角色 | 查看任务 | 运行、审批和上传 | 发布 Agent | 查看审计日志 |
| --- | --- | --- | --- | --- |
| `viewer` | 只能查看自己的任务 | 不允许 | 不允许 | 不允许 |
| `member` | 管理自己的任务 | 允许 | 不允许 | 不允许 |
| `admin` | 管理自己的任务 | 允许 | 允许 | 允许 |
| `owner` | 拥有当前租户的全部权限 | 允许 | 允许 | 允许 |

角色校验通过后，系统仍会继续进行资源归属校验。同一租户中的普通用户不能因为拥有
`member` 或 `admin` 角色，就读取其他用户的会话、运行记录、上传文件或生成制品。

## 审计日志

以下行为会写入只追加的 `audit_logs` 表：

- 注册、登录、刷新会话和退出登录；
- 修改类 API 请求；
- 审批操作；
- 制品内容下载；
- 其他需要追踪的安全敏感操作。

`owner` 和 `admin` 可以通过 `GET /v1/auth/audit-logs` 查询当前租户的审计记录。

审计日志用于回答“谁在什么时间，对哪个资源执行了什么操作，结果如何”，
但不应直接记录密码、Access Token、Refresh Token 或 OAuth Client Secret。

## 制品与 MinIO

MinIO 用于保存 Agent 运行过程中生成的报告、文档、图片和其他制品文件。
数据库保存制品元数据及所属会话、运行和用户关系，MinIO 保存实际文件内容。

MinIO Bucket 保持私有。用户下载制品时必须经过 Harness API，API 会依次校验：

1. 用户登录状态；
2. 当前租户和角色权限；
3. 制品所属运行与会话；
4. 当前用户是否拥有该资源。

本地 Compose 只将 MinIO API 和管理端口绑定到 `127.0.0.1`。
生产部署通常应完全取消 MinIO 的宿主机端口映射，只允许 API 通过内部网络访问。

## 推荐的验证方式

### 日常本地回归

不配置 Google/GitHub，重点验证：

- 注册、登录和退出；
- Access Token 过期后的自动刷新；
- Refresh Token 轮换和重复使用拦截；
- 不同用户之间的任务、会话和制品隔离；
- `viewer`、`member`、`admin`、`owner` 权限边界；
- 审批和制品下载是否产生审计记录。

### SSO 集成验证

使用独立的开发 OAuth 应用，分别验证：

- 首次使用 Google/GitHub 登录时自动创建或关联账号；
- 已验证邮箱与现有本地账号的安全关联；
- OAuth state 不匹配时拒绝登录；
- PKCE verifier 丢失或错误时拒绝登录；
- 服务商拒绝授权或回调失败时返回可理解的错误；
- SSO 登录后仍执行相同的租户、角色与资源归属校验。

## 生产环境检查清单

1. 为 `HARNESS_API_BEARER_TOKEN` 和 `HARNESS_AUTH_JWT_SECRET` 分别生成不同的随机值，长度至少为 32 个字符；
2. 将 `AUTH_PUBLIC_URL` 设置为生产环境唯一的 HTTPS 地址；
3. 设置 `AUTH_COOKIE_SECURE=true`；
4. 在 Google/GitHub OAuth 应用中登记完全一致的 HTTPS 回调地址；
5. 不要在 Web 容器或浏览器环境变量中配置 OAuth Client Secret；
6. 创建初始 `owner` 后，建议设置 `HARNESS_AUTH_ALLOW_REGISTRATION=false`，停止公开注册；
7. 后续用户通过 SSO 或管理员邀请、创建流程加入；
8. API、PostgreSQL、Redis 和 MinIO 仅部署在私有网络；
9. 不公开 PostgreSQL、Redis、MinIO 管理端口；
10. 为登录失败、权限拒绝、审批和制品下载配置审计与告警；
11. 根据组织安全策略设置审计日志保留周期与备份方案；
12. 定期轮换内部服务凭证、JWT 密钥和 OAuth Client Secret。
