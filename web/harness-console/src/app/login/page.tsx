"use client";

import { type FormEvent, useEffect, useState } from "react";

type AuthConfig = {
  registration_enabled: boolean;
  providers: { google: boolean; github: boolean };
};

const ERROR_MESSAGES: Record<string, string> = {
  sso_unavailable: "该登录方式尚未配置。",
  sso_state_invalid: "登录请求已经过期，请重新尝试。",
  sso_exchange_failed: "第三方登录没有完成，请重试。",
};

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    fetch("/api/auth/config", { cache: "no-store" })
      .then((response) => response.json())
      .then((value: AuthConfig) => setConfig(value))
      .catch(() => setError("认证服务暂时不可用。"));
    const code = new URLSearchParams(window.location.search).get("error");
    if (code) setError(ERROR_MESSAGES[code] ?? "登录没有完成，请重新尝试。");
    if (new URLSearchParams(window.location.search).get("password") === "changed") {
      setNotice("密码已更新，请使用新密码重新登录。");
    }
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const payload = {
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
      ...(mode === "register"
        ? { display_name: String(form.get("display_name") ?? "") }
        : {}),
    };
    try {
      const response = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = (await response.json()) as {
        error?: { message?: string };
      };
      if (!response.ok) {
        setError(result.error?.message ?? "登录信息无法验证。");
        return;
      }
      window.location.replace("/");
    } catch {
      setError("认证服务暂时不可用。");
    } finally {
      setPending(false);
    }
  }

  const hasSso = Boolean(config?.providers.google || config?.providers.github);
  return (
    <main className="login-shell">
      <section className="login-context" aria-label="Agent Harness 简介">
        <div className="login-brand">
          <span className="brand-mark">H</span>
          <div>
            <strong>Agent Harness</strong>
            <span>智能任务工作台</span>
          </div>
        </div>
        <div className="login-thesis">
          <p className="login-eyebrow">从意图到可审计的执行</p>
          <h1>把复杂任务交给 Agent，关键动作仍由你掌控。</h1>
          <p>任务、工具、审批与制品在同一条执行轨迹中留痕。</p>
        </div>
        <ol className="login-trace" aria-label="示例执行轨迹">
          <li><span>01</span><div><strong>理解任务</strong><small>建立范围与执行计划</small></div><em>完成</em></li>
          <li><span>02</span><div><strong>隔离执行</strong><small>工具与文件在沙箱运行</small></div><em>受控</em></li>
          <li><span>03</span><div><strong>人工确认</strong><small>高风险动作等待批准</small></div><em>可审计</em></li>
        </ol>
      </section>

      <section className="login-panel" aria-label={mode === "login" ? "登录" : "创建账户"}>
        <div className="login-card">
          <header>
            <p>{mode === "login" ? "欢迎回来" : "开始使用"}</p>
            <h2>{mode === "login" ? "登录工作台" : "创建账户"}</h2>
            <span>{mode === "login" ? "继续处理你的任务与审批。" : "首位注册用户将成为工作区所有者。"}</span>
          </header>

          {hasSso && (
            <div className="sso-actions">
              {config?.providers.google && <a href="/api/auth/oauth/google/start"><GoogleIcon />使用 Google 登录</a>}
              {config?.providers.github && <a href="/api/auth/oauth/github/start"><GithubIcon />使用 GitHub 登录</a>}
            </div>
          )}
          {hasSso && <div className="login-divider"><span>或使用邮箱</span></div>}

          <form onSubmit={submit}>
            {mode === "register" && (
              <label>姓名<input name="display_name" autoComplete="name" required placeholder="你希望显示的名称" /></label>
            )}
            <label>邮箱<input name="email" type="email" autoComplete="email" required placeholder="name@company.com" /></label>
            <label>密码<input name="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={10} placeholder="至少 10 位，含大小写与数字" /></label>
            {error && <p className="login-error" role="alert">{error}</p>}
            {notice && <p className="login-notice" role="status">{notice}</p>}
            <button className="login-submit" type="submit" disabled={pending}>{pending ? "正在验证…" : mode === "login" ? "登录" : "创建并登录"}</button>
          </form>

          {config?.registration_enabled && (
            <button className="auth-mode-switch" type="button" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
              {mode === "login" ? "没有账户？创建一个" : "已有账户？返回登录"}
            </button>
          )}
        </div>
        <p className="login-security-note"><span aria-hidden="true">●</span> 登录会话使用 HttpOnly Cookie，身份由 API 验签。</p>
      </section>
    </main>
  );
}

function GoogleIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.4 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.3a4.5 4.5 0 0 1-2 3v2.5h3.2c1.9-1.8 2.9-4.3 2.9-7.3Z" fill="#4285F4"/><path d="M12 21.8c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1a5.8 5.8 0 0 1-5.4-4H3.3v2.6a10 10 0 0 0 8.7 5.3Z" fill="#34A853"/><path d="M6.6 13.9a6 6 0 0 1 0-3.8V7.5H3.3a10 10 0 0 0 0 9l3.3-2.6Z" fill="#FBBC05"/><path d="M12 6.1c1.6 0 3 .5 4.1 1.6l3-3A10 10 0 0 0 3.3 7.5l3.3 2.6a5.8 5.8 0 0 1 5.4-4Z" fill="#EA4335"/></svg>;
}

function GithubIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .8a11.4 11.4 0 0 0-3.6 22.2c.6.1.8-.2.8-.5v-2c-3.3.7-4-1.4-4-1.4-.6-1.4-1.4-1.8-1.4-1.8-1.1-.8.1-.8.1-.8 1.2.1 1.9 1.3 1.9 1.3 1.1 1.9 2.9 1.3 3.6 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11 11 0 0 1 6 0C14.3 3.8 15.3 4 15.3 4c.6 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v4c0 .3.2.6.8.5A11.4 11.4 0 0 0 12 .8Z"/></svg>;
}
