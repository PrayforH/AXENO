"use client";

import { useEffect, useMemo, useState } from "react";
import { AgentSelector } from "../components/agent-selector";
import { ApprovalCard } from "../components/approval-card";
import { ArtifactList } from "../components/artifact-list";
import { RunStatus } from "../components/run-status";
import { ToolCard } from "../components/tool-card";
import type { AguiEvent } from "../lib/agui";
import { HarnessClient, type Artifact } from "../lib/harness-client";

const STORAGE_KEY = "harness-console-run";

export default function Home() {
  const [baseUrl, setBaseUrl] = useState("http://localhost:8000");
  const [agent, setAgent] = useState("echo-agent");
  const [version, setVersion] = useState("0.1.0");
  const [prompt, setPrompt] = useState("请读取项目配置并简要说明这个 Harness。");
  const [runId, setRunId] = useState("");
  const [status, setStatus] = useState("idle");
  const [events, setEvents] = useState<AguiEvent[]>([]);
  const [lastEventId, setLastEventId] = useState<string>();
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [error, setError] = useState("");
  const client = useMemo(() => new HarnessClient(baseUrl, { tenantId: "local", userId: "developer" }), [baseUrl]);

  useEffect(() => { const saved = localStorage.getItem(STORAGE_KEY); if (saved) setRunId(saved); }, []);
  useEffect(() => { if (!runId) return; localStorage.setItem(STORAGE_KEY, runId); void client.getRun(runId).then((run) => setStatus(run.status)).catch(() => localStorage.removeItem(STORAGE_KEY)); }, [client, runId]);

  async function start() {
    setError(""); setEvents([]); setLastEventId(undefined);
    try {
      await client.publishAgent("tests/fixtures/agents/echo-agent/agent.yaml").catch(() => undefined);
      const session = await client.createSession(agent, version);
      const run = await client.createRun(session.session_id, prompt);
      setRunId(run.run_id); setStatus(run.status);
      await client.events(run.run_id, undefined, (id, event) => { setLastEventId(id); setEvents((current) => [...current, event]); });
      const latest = await client.getRun(run.run_id); setStatus(latest.status);
      setArtifacts(await client.artifacts(run.run_id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }

  const approval = events.findLast((event) => event.type === "CUSTOM" && event.name === "harness.approval.v1");
  const approvalId = approval && typeof approval.value === "object" && approval.value ? String((approval.value as Record<string, unknown>).approval_id ?? "") : "";
  const tool = events.findLast((event) => event.type === "TOOL_CALL_START");

  return <main className="shell"><header className="header"><div><h1>Claude Agent Harness Console</h1><p>CopilotKit / AG-UI 本地验证面板 · Langfuse 默认关闭</p></div><RunStatus status={status} /></header><div className="grid"><section className="panel stack"><label className="label">Harness API<input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} /></label><AgentSelector name={agent} version={version} onName={setAgent} onVersion={setVersion} /><label className="label">Prompt<textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} /></label><div className="row"><button onClick={() => void start()}>启动 Run</button><button className="secondary" disabled={!runId} onClick={() => void client.cancel(runId).then((run) => setStatus(run.status))}>取消</button><button className="secondary" disabled={!runId} onClick={() => void client.events(runId, lastEventId, (id, event) => { setLastEventId(id); setEvents((current) => [...current, event]); })}>重连事件</button></div>{error && <div className="card">{error}</div>}{approvalId && <ApprovalCard id={approvalId} onDecision={(decision) => void client.approve(approvalId, decision).then(() => setStatus(decision))} />}{tool && <ToolCard name={String(tool.toolCallName ?? "tool")} args={tool} />}<ArtifactList items={artifacts} url={(id) => client.artifactUrl(id)} /></section><section className="panel"><h2>AG-UI Events</h2><div className="event-list">{events.length === 0 && <p className="muted">运行后将在这里看到标准事件流。</p>}{events.map((event, index) => <div className="event" key={`${event.type}-${index}`}><code>{event.type}</code><pre>{JSON.stringify(event, null, 2)}</pre></div>)}</div></section></div></main>;
}

