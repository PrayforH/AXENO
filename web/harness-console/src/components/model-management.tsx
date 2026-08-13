"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import styles from "./model-management.module.css";

type ModelType = "chat" | "vision" | "image_generation";
type ApiFormat = "anthropic_compatible" | "openai_compatible" | "openai_images";

type ManagedModel = {
  routeId: string;
  label: string;
  modelType: ModelType;
  provider: string;
  model: string;
  baseUrl: string | null;
  apiFormat: ApiFormat;
  authScheme: "bearer" | "x-api-key";
  capabilities: string[];
  enabled: boolean;
  credentialConfigured: boolean;
  version: number;
};

type ModelState = {
  revision: number;
  models: ManagedModel[];
  agentModelBindings: Record<string, string>;
};

type AgentItem = { name: string; display_name: string };

const TYPE_COPY: Record<ModelType, { label: string; mark: string; description: string }> = {
  chat: { label: "对话", mark: "C", description: "文本理解、工具调用与流式回答" },
  vision: { label: "视觉", mark: "V", description: "同时理解文本、图片与文档截图" },
  image_generation: { label: "图像生成", mark: "I", description: "通过独立接口生成图片，不参与对话路由" },
};

const EMPTY_STATE: ModelState = { revision: 1, models: [], agentModelBindings: {} };

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: "no-store", ...init });
  const payload = (await response.json().catch(() => null)) as
    | T
    | { error?: { message?: string } }
    | null;
  if (!response.ok) {
    const message = payload && typeof payload === "object" && "error" in payload
      ? payload.error?.message
      : null;
    throw new Error(message || `请求失败（${response.status}）`);
  }
  return payload as T;
}

function routeIdFromLabel(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/^[^a-z]+/, "");
}

export function ModelManagement() {
  const [state, setState] = useState<ModelState>(EMPTY_STATE);
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [filter, setFilter] = useState<"all" | ModelType>("all");
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<ManagedModel | null | undefined>(undefined);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  async function refresh() {
    const [models, catalog] = await Promise.all([
      api<ModelState>("/api/studio/models"),
      api<AgentItem[]>("/api/harness/agents").catch(() => []),
    ]);
    setState(models);
    setAgents(
      catalog.filter(
        (item, index, all) => all.findIndex((candidate) => candidate.name === item.name) === index,
      ),
    );
  }

  useEffect(() => {
    let active = true;
    refresh()
      .catch((error: unknown) => {
        if (active) setMessage({ kind: "error", text: error instanceof Error ? error.message : "模型配置暂时不可用。" });
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const visible = useMemo(
    () => state.models.filter((model) => filter === "all" || model.modelType === filter),
    [filter, state.models],
  );
  const conversational = state.models.filter(
    (model) => model.enabled && model.modelType !== "image_generation" && model.baseUrl && model.credentialConfigured,
  );

  async function testConnection(model: ManagedModel) {
    setBusy(`test:${model.routeId}`);
    setMessage(null);
    try {
      const result = await api<{ message: string; latencyMs: number }>(
        `/api/studio/models/${encodeURIComponent(model.routeId)}/test`,
        { method: "POST" },
      );
      setMessage({ kind: "success", text: `${model.label}：${result.message}（${result.latencyMs} ms）` });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "模型连接失败。" });
    } finally {
      setBusy("");
    }
  }

  async function disable(model: ManagedModel) {
    if (!window.confirm(`停用“${model.label}”？已绑定的 Agent 将无法使用该路由。`)) return;
    setBusy(`disable:${model.routeId}`);
    try {
      const next = await api<ModelState>(
        `/api/studio/models/${encodeURIComponent(model.routeId)}?expectedRevision=${state.revision}`,
        { method: "DELETE" },
      );
      setState(next);
      setMessage({ kind: "success", text: `${model.label} 已停用。` });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "模型未能停用。" });
    } finally {
      setBusy("");
    }
  }

  async function bindAgent(agentName: string, routeId: string) {
    setBusy(`bind:${agentName}`);
    try {
      const next = await api<ModelState>(
        `/api/studio/models/agent-bindings/${encodeURIComponent(agentName)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expectedRevision: state.revision, routeId }),
        },
      );
      setState(next);
      setMessage({ kind: "success", text: "Agent 默认模型已更新，新任务立即生效。" });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "默认模型未能更新。" });
    } finally {
      setBusy("");
    }
  }

  return (
    <div className={styles.controlPlane}>
      <div className={styles.guardrail}>
        <span className={styles.lock} aria-hidden="true">⌁</span>
        <div><strong>凭据由服务端托管</strong><small>API Key 加密保存且不回传浏览器；只有 Owner / Admin 可以查看连接信息或修改配置。</small></div>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.filters} aria-label="模型类型">
          {(["all", "chat", "vision", "image_generation"] as const).map((type) => (
            <button key={type} type="button" className={filter === type ? styles.filterActive : ""} onClick={() => setFilter(type)}>
              {type === "all" ? `全部 ${state.models.length}` : `${TYPE_COPY[type].label} ${state.models.filter((item) => item.modelType === type).length}`}
            </button>
          ))}
        </div>
        <button type="button" className={styles.addButton} onClick={() => setEditing(null)}>+ 添加模型</button>
      </div>

      {message && <p className={`${styles.message} ${styles[message.kind]}`} role="status">{message.text}</p>}
      {loading ? <p className={styles.empty}>正在读取模型配置…</p> : (
        <div className={styles.grid}>
          {visible.map((model) => (
            <article className={styles.modelCard} key={model.routeId}>
              <span className={`${styles.typeMark} ${styles[model.modelType]}`} aria-hidden="true">{TYPE_COPY[model.modelType].mark}</span>
              <div className={styles.modelCopy}>
                <div className={styles.cardTitle}>
                  <strong>{model.label}</strong>
                  <span className={model.enabled ? styles.ready : styles.disabled}>{model.enabled ? "已启用" : "已停用"}</span>
                </div>
                <p>{model.model}</p>
                <small>{model.provider} · {TYPE_COPY[model.modelType].description}</small>
                <div className={styles.statusRow}>
                  <span data-ok={Boolean(model.baseUrl)}>端点{model.baseUrl ? "已配置" : "待配置"}</span>
                  <span data-ok={model.credentialConfigured}>密钥{model.credentialConfigured ? "已保存" : "待配置"}</span>
                </div>
              </div>
              <div className={styles.cardActions}>
                <button type="button" onClick={() => setEditing(model)}>编辑</button>
                <button type="button" disabled={!model.baseUrl || !model.credentialConfigured || busy !== ""} onClick={() => void testConnection(model)}>
                  {busy === `test:${model.routeId}` ? "测试中" : "测试"}
                </button>
                {model.enabled && <button type="button" className={styles.danger} disabled={busy !== ""} onClick={() => void disable(model)}>停用</button>}
              </div>
            </article>
          ))}
          <button type="button" className={styles.emptyCard} onClick={() => setEditing(null)}>
            <span>+</span><strong>添加模型</strong><small>对话、视觉或图像生成</small>
          </button>
        </div>
      )}

      <div className={styles.bindings}>
        <div><strong>Agent 默认模型</strong><small>替代内置 Agent 包中的后台固定值；只影响新任务，任务中仍可临时切换。</small></div>
        {agents.length === 0 ? <p className={styles.empty}>暂无可配置的 Agent。</p> : agents.map((agent) => (
          <label key={agent.name}>
            <span><strong>{agent.display_name}</strong><small>{agent.name}</small></span>
            <select
              value={state.agentModelBindings[agent.name] ?? ""}
              disabled={busy !== "" || conversational.length === 0}
              onChange={(event) => void bindAgent(agent.name, event.target.value)}
            >
              <option value="" disabled>选择默认模型</option>
              {conversational.map((model) => <option key={model.routeId} value={model.routeId}>{model.label} · {TYPE_COPY[model.modelType].label}</option>)}
            </select>
          </label>
        ))}
      </div>

      {editing !== undefined && (
        <ModelDialog
          model={editing}
          revision={state.revision}
          onClose={() => setEditing(undefined)}
          onSaved={(next, label) => {
            setState(next);
            setEditing(undefined);
            setMessage({ kind: "success", text: `${label} 已保存。` });
          }}
        />
      )}
    </div>
  );
}

function ModelDialog({
  model,
  revision,
  onClose,
  onSaved,
}: {
  model: ManagedModel | null;
  revision: number;
  onClose: () => void;
  onSaved: (next: ModelState, label: string) => void;
}) {
  const [type, setType] = useState<ModelType>(model?.modelType ?? "chat");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const label = String(form.get("label") ?? "").trim();
    const routeId = model?.routeId ?? routeIdFromLabel(String(form.get("routeId") ?? ""));
    if (!routeId) {
      setError("路由 ID 需以英文字母开头，只能包含小写字母、数字和连字符。");
      setPending(false);
      return;
    }
    const apiKey = String(form.get("apiKey") ?? "").trim();
    try {
      const next = await api<ModelState>(`/api/studio/models/${encodeURIComponent(routeId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expectedRevision: revision,
          label,
          modelType: type,
          provider: String(form.get("provider") ?? ""),
          model: String(form.get("model") ?? ""),
          baseUrl: String(form.get("baseUrl") ?? ""),
          apiFormat: type === "image_generation" ? "openai_images" : String(form.get("apiFormat") ?? "anthropic_compatible"),
          authScheme: String(form.get("authScheme") ?? "bearer"),
          apiKey: apiKey || null,
          enabled: true,
        }),
      });
      onSaved(next, label);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "模型配置未能保存。请检查字段后重试。");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={styles.backdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="model-dialog-title">
        <header>
          <div><span className={`${styles.typeMark} ${styles[type]}`}>{TYPE_COPY[type].mark}</span><span><strong id="model-dialog-title">{model ? "编辑模型" : "添加模型"}</strong><small>{TYPE_COPY[type].description}</small></span></div>
          <button type="button" aria-label="关闭" onClick={onClose}>×</button>
        </header>
        <form onSubmit={save}>
          <fieldset className={styles.typePicker}>
            <legend>模型类型</legend>
            {(["chat", "vision", "image_generation"] as const).map((item) => (
              <label key={item} className={type === item ? styles.typeActive : ""}>
                <input type="radio" name="modelType" value={item} checked={type === item} onChange={() => setType(item)} />
                <span>{TYPE_COPY[item].mark}</span><strong>{TYPE_COPY[item].label}</strong>
              </label>
            ))}
          </fieldset>
          <div className={styles.formGrid}>
            <label>显示名称<input name="label" defaultValue={model?.label ?? ""} required placeholder="例如：客服视觉模型" /></label>
            <label>路由 ID<input name="routeId" defaultValue={model?.routeId ?? ""} disabled={Boolean(model)} required placeholder="例如：customer-vision" pattern="[a-z][a-z0-9-]*" /></label>
            <label>服务商<input name="provider" defaultValue={model?.provider ?? "OpenAI"} required placeholder="OpenAI / Anthropic / 自定义" /></label>
            <label>模型名称<input name="model" defaultValue={model?.model ?? ""} required placeholder="服务商使用的实际模型名" /></label>
            <label className={styles.full}>Base URL<input name="baseUrl" type="url" defaultValue={model?.baseUrl ?? ""} required placeholder="https://api.example.com/v1" /></label>
            {type !== "image_generation" && (
              <label>接口格式<select name="apiFormat" defaultValue={model?.apiFormat ?? "anthropic_compatible"}><option value="anthropic_compatible">Anthropic 兼容</option><option value="openai_compatible">OpenAI 兼容</option></select></label>
            )}
            <label>鉴权方式<select name="authScheme" defaultValue={model?.authScheme ?? "bearer"}><option value="bearer">Bearer Token</option><option value="x-api-key">x-api-key</option></select></label>
            <label className={styles.full}>API Key<input name="apiKey" type="password" autoComplete="new-password" required={!model?.credentialConfigured} placeholder={model?.credentialConfigured ? "已安全保存；留空则保持不变" : "输入 API Key"} /><small>保存后不会再次显示明文。</small></label>
          </div>
          {error && <p className={`${styles.message} ${styles.error}`} role="alert">{error}</p>}
          <footer><button type="button" onClick={onClose}>取消</button><button type="submit" className={styles.save} disabled={pending}>{pending ? "正在保存…" : "保存模型"}</button></footer>
        </form>
      </div>
    </div>
  );
}
