"use client";

import { useEffect, useMemo, useState } from "react";
import {
  StudioApiError,
  studioClient,
  type StudioAgentTrigger,
  type StudioCreatedAgentTrigger,
  type StudioEnvironment,
  type StudioEnvironmentName,
} from "../../lib/studio-client";
import styles from "./agent-trigger-control-plane.module.css";

type AgentTriggerControlPlaneProps = {
  agentName: string;
  publishedVersion: string | null;
  environments: StudioEnvironment[];
  canManage: boolean;
};

function endpoint(triggerId: string) {
  return `/webhooks/agent-triggers/${encodeURIComponent(triggerId)}`;
}

export function AgentTriggerControlPlane({
  agentName,
  publishedVersion,
  environments,
  canManage,
}: AgentTriggerControlPlaneProps) {
  const [triggers, setTriggers] = useState<StudioAgentTrigger[]>([]);
  const [name, setName] = useState("Webhook 入口");
  const [environment, setEnvironment] =
    useState<StudioEnvironmentName>("production");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [issued, setIssued] = useState<StudioCreatedAgentTrigger | null>(null);
  const deployedEnvironments = useMemo(
    () => environments.filter((item) => item.healthySnapshotId),
    [environments],
  );

  useEffect(() => {
    const preferred =
      deployedEnvironments.find((item) => item.name === "production")
      ?? deployedEnvironments[0];
    if (preferred) setEnvironment(preferred.name);
  }, [deployedEnvironments]);

  useEffect(() => {
    let active = true;
    if (!publishedVersion || !agentName) {
      setTriggers([]);
      return;
    }
    studioClient
      .listTriggers(agentName)
      .then((items) => {
        if (active) setTriggers(items);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "触发器读取失败");
        }
      });
    return () => {
      active = false;
    };
  }, [agentName, publishedVersion]);

  async function createTrigger() {
    setBusy("create");
    setError("");
    try {
      const created = await studioClient.createTrigger(
        agentName,
        name.trim(),
        environment,
      );
      setIssued(created);
      setTriggers((current) => [created.trigger, ...current]);
      setName("Webhook 入口");
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy("");
    }
  }

  async function toggle(trigger: StudioAgentTrigger) {
    setBusy(`toggle:${trigger.triggerId}`);
    setError("");
    try {
      const updated = await studioClient.updateTrigger(trigger, {
        name: trigger.name,
        enabled: !trigger.enabled,
      });
      setTriggers((current) =>
        current.map((item) =>
          item.triggerId === updated.triggerId ? updated : item,
        ),
      );
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy("");
    }
  }

  async function rotate(trigger: StudioAgentTrigger) {
    setBusy(`rotate:${trigger.triggerId}`);
    setError("");
    try {
      const rotated = await studioClient.rotateTriggerSecret(trigger);
      setIssued(rotated);
      setTriggers((current) =>
        current.map((item) =>
          item.triggerId === rotated.trigger.triggerId
            ? rotated.trigger
            : item,
        ),
      );
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy("");
    }
  }

  async function copy(value: string) {
    await navigator.clipboard.writeText(value);
  }

  async function copyCurl(created: StudioCreatedAgentTrigger) {
    const url = `${window.location.origin}${endpoint(created.trigger.triggerId)}`;
    await copy(
      [
        `curl -X POST '${url}' \\`,
        `  -H 'Authorization: Bearer ${created.secret}' \\`,
        "  -H 'Idempotency-Key: your-event-id' \\",
        "  -H 'Content-Type: application/json' \\",
        `  -d '{"prompt":"描述要执行的任务"}'`,
      ].join("\n"),
    );
  }

  return (
    <section className={styles.controlPlane} aria-label="Agent 触发器">
      <header>
        <div>
          <span>INVOCATION</span>
          <strong>外部触发器</strong>
          <small>
            外部系统复用当前环境快照，并进入同一套运行、审批、取消、制品与 Trace。
          </small>
        </div>
        <em>{triggers.filter((item) => item.enabled).length} 个启用</em>
      </header>

      {!publishedVersion ? (
        <p className={styles.empty}>发布不可变版本后才能创建外部入口。</p>
      ) : deployedEnvironments.length === 0 ? (
        <p className={styles.empty}>至少需要一个已经健康部署的环境。</p>
      ) : (
        <>
          {canManage && (
            <div className={styles.creator}>
              <label>
                <span>名称</span>
                <input
                  value={name}
                  maxLength={120}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              <label>
                <span>环境</span>
                <select
                  value={environment}
                  onChange={(event) =>
                    setEnvironment(event.target.value as StudioEnvironmentName)
                  }
                >
                  {deployedEnvironments.map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.name.toUpperCase()}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={!name.trim() || busy === "create"}
                onClick={() => void createTrigger()}
              >
                {busy === "create" ? "创建中…" : "创建 Webhook"}
              </button>
            </div>
          )}

          {issued && (
            <aside className={styles.secretCard} aria-live="polite">
              <div>
                <span>只显示一次</span>
                <strong>立即保存触发密钥</strong>
                <small>关闭后无法找回，只能轮换。旧密钥在轮换后立即失效。</small>
              </div>
              <code>{issued.secret}</code>
              <div className={styles.secretActions}>
                <button type="button" onClick={() => void copy(issued.secret)}>
                  复制密钥
                </button>
                <button type="button" onClick={() => void copyCurl(issued)}>
                  复制 cURL
                </button>
                <button type="button" onClick={() => setIssued(null)}>
                  我已保存
                </button>
              </div>
            </aside>
          )}

          <div className={styles.triggerList}>
            {triggers.map((trigger) => (
              <article key={trigger.triggerId} data-enabled={trigger.enabled}>
                <span className={styles.state}>
                  {trigger.enabled ? "已启用" : "已停用"}
                </span>
                <div>
                  <strong>{trigger.name}</strong>
                  <small>
                    {trigger.environment.toUpperCase()} · revision {trigger.revision}
                    {trigger.lastInvokedAt
                      ? ` · 最近调用 ${new Date(trigger.lastInvokedAt).toLocaleString("zh-CN")}`
                      : " · 尚未调用"}
                  </small>
                  <code>{endpoint(trigger.triggerId)}</code>
                </div>
                <div className={styles.actions}>
                  <button
                    type="button"
                    onClick={() =>
                      void copy(`${window.location.origin}${endpoint(trigger.triggerId)}`)
                    }
                  >
                    复制地址
                  </button>
                  {canManage && (
                    <>
                      <button
                        type="button"
                        disabled={Boolean(busy)}
                        onClick={() => void rotate(trigger)}
                      >
                        {busy === `rotate:${trigger.triggerId}` ? "轮换中…" : "轮换密钥"}
                      </button>
                      <button
                        type="button"
                        disabled={Boolean(busy)}
                        onClick={() => void toggle(trigger)}
                      >
                        {busy === `toggle:${trigger.triggerId}`
                          ? "更新中…"
                          : trigger.enabled
                            ? "停用"
                            : "启用"}
                      </button>
                    </>
                  )}
                </div>
              </article>
            ))}
            {triggers.length === 0 && (
              <p className={styles.empty}>还没有外部入口。</p>
            )}
          </div>
        </>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </section>
  );
}

function message(reason: unknown) {
  if (reason instanceof StudioApiError) return reason.message;
  return reason instanceof Error ? reason.message : "操作失败";
}
