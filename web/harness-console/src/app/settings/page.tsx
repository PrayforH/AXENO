"use client";

import { type FormEvent, useState } from "react";
import { AuthProvider, useAuth } from "../../components/auth-provider";

const ROLE_LABELS = {
  owner: "所有者",
  admin: "管理员",
  member: "成员",
  viewer: "只读成员",
} as const;

type Message = { kind: "success" | "error"; text: string } | null;

function errorMessage(payload: unknown, fallback: string): string {
  if (
    payload &&
    typeof payload === "object" &&
    "error" in payload &&
    payload.error &&
    typeof payload.error === "object" &&
    "message" in payload.error &&
    typeof payload.error.message === "string"
  ) {
    return payload.error.message;
  }
  return fallback;
}

function SettingsContent() {
  const { user, membership, passwordEnabled } = useAuth();
  const [profileMessage, setProfileMessage] = useState<Message>(null);
  const [passwordMessage, setPasswordMessage] = useState<Message>(null);
  const [profilePending, setProfilePending] = useState(false);
  const [passwordPending, setPasswordPending] = useState(false);

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProfilePending(true);
    setProfileMessage(null);
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/auth/profile", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: String(form.get("display_name") ?? "") }),
      });
      const payload = (await response.json()) as unknown;
      if (!response.ok) {
        setProfileMessage({ kind: "error", text: errorMessage(payload, "个人资料未能保存。") });
        return;
      }
      setProfileMessage({ kind: "success", text: "个人资料已保存。" });
    } catch {
      setProfileMessage({ kind: "error", text: "认证服务暂时不可用。" });
    } finally {
      setProfilePending(false);
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPasswordPending(true);
    setPasswordMessage(null);
    const form = new FormData(event.currentTarget);
    const currentPassword = String(form.get("current_password") ?? "");
    const newPassword = String(form.get("new_password") ?? "");
    const confirmPassword = String(form.get("confirm_password") ?? "");
    if (newPassword !== confirmPassword) {
      setPasswordMessage({ kind: "error", text: "两次输入的新密码不一致。" });
      setPasswordPending(false);
      return;
    }
    try {
      const response = await fetch("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      if (!response.ok) {
        const payload = (await response.json()) as unknown;
        setPasswordMessage({ kind: "error", text: errorMessage(payload, "密码未能更新。") });
        return;
      }
      window.location.replace("/login?password=changed");
    } catch {
      setPasswordMessage({ kind: "error", text: "认证服务暂时不可用。" });
    } finally {
      setPasswordPending(false);
    }
  }

  return (
    <main className="settings-shell">
      <header className="settings-header">
        <a className="settings-brand" href="/" aria-label="返回智能任务助手">
          <span className="brand-mark" aria-hidden="true">H</span>
          <span><strong>智能任务助手</strong><small>Agent Harness</small></span>
        </a>
        <a className="settings-back" href="/">返回工作台</a>
      </header>

      <div className="settings-layout">
        <aside className="settings-index" aria-label="设置目录">
          <p>设置</p>
          <a href="#profile">个人资料</a>
          <a href="#security">账户安全</a>
          <a href="#data">我的数据</a>
          <a href="#session">登录会话</a>
        </aside>

        <div className="settings-content">
          <header className="settings-title">
            <p>账户设置</p>
            <h1>管理你的身份与登录安全</h1>
            <span>这些设置只影响当前用户，不会改变 Agent 或工作区运行配置。</span>
          </header>

          <section className="settings-section" id="profile">
            <div className="settings-section-copy">
              <h2>个人资料</h2>
              <p>显示名称会出现在账户菜单和审计记录中。</p>
            </div>
            <form className="settings-form" onSubmit={saveProfile}>
              <label>
                显示名称
                <input name="display_name" defaultValue={user.display_name} required maxLength={160} autoComplete="name" />
              </label>
              <label>
                登录邮箱
                <input value={user.email} readOnly aria-readonly="true" />
                <small>邮箱暂不支持自行修改。</small>
              </label>
              <div className="settings-facts">
                <span><small>工作区角色</small><strong>{ROLE_LABELS[membership.role]}</strong></span>
                <span><small>工作区</small><code>{membership.tenant_id}</code></span>
              </div>
              {profileMessage && <p className={`settings-message ${profileMessage.kind}`} role="status">{profileMessage.text}</p>}
              <div className="settings-form-action">
                <button type="submit" disabled={profilePending}>{profilePending ? "正在保存…" : "保存资料"}</button>
              </div>
            </form>
          </section>

          <section className="settings-section" id="security">
            <div className="settings-section-copy">
              <h2>账户安全</h2>
              <p>修改密码后会撤销所有刷新会话；其他设备的短期凭证到期后无法续期。</p>
            </div>
            {passwordEnabled ? (
              <form className="settings-form" onSubmit={changePassword}>
                <label>当前密码<input name="current_password" type="password" required autoComplete="current-password" /></label>
                <label>新密码<input name="new_password" type="password" required minLength={10} autoComplete="new-password" placeholder="至少 10 位，含大小写字母和数字" /></label>
                <label>确认新密码<input name="confirm_password" type="password" required minLength={10} autoComplete="new-password" /></label>
                {passwordMessage && <p className={`settings-message ${passwordMessage.kind}`} role="alert">{passwordMessage.text}</p>}
                <div className="settings-form-action">
                  <button type="submit" disabled={passwordPending}>{passwordPending ? "正在更新…" : "修改密码"}</button>
                </div>
              </form>
            ) : (
              <div className="settings-form settings-empty">
                <strong>当前账户通过单点登录验证</strong>
                <p>请在 Google 或 GitHub 中管理密码。本系统不会直接保存第三方账户密码。</p>
              </div>
            )}
          </section>

          <section className="settings-section" id="data">
            <div className="settings-section-copy">
              <h2>我的数据</h2>
              <p>导出或删除当前用户在 Harness 中产生的会话、文件、记忆与观测数据。</p>
            </div>
            <div className="settings-form settings-session">
              <div><span className="settings-session-dot" aria-hidden="true" /><span><strong>数据生命周期</strong><small>删除操作会先检查 Legal Hold，再按外部系统逐项执行。</small></span></div>
              <a href="/studio/data">管理我的数据</a>
            </div>
          </section>

          <section className="settings-section" id="session">
            <div className="settings-section-copy">
              <h2>登录会话</h2>
              <p>退出后将清除当前浏览器凭证，并撤销本次刷新令牌。</p>
            </div>
            <div className="settings-form settings-session">
              <div><span className="settings-session-dot" aria-hidden="true" /><span><strong>当前浏览器</strong><small>会话有效</small></span></div>
              <a href="/api/auth/logout">退出登录</a>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

export default function SettingsPage() {
  return <AuthProvider><SettingsContent /></AuthProvider>;
}
