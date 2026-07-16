"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  BUILTIN_TOOLS,
  DEFAULT_STUDIO_DRAFT,
  MCP_OPTIONS,
  MODEL_ROUTES,
  PUBLISHED_SUBAGENTS,
  POLICY_OPTIONS,
  REQUIRED_PROMPT_HEADINGS,
  evaluateStudioDraft,
  restoreStudioDraft,
  type StudioDraft,
  type StudioSection,
  type StudioSubagent,
} from "../../lib/agent-studio";
import styles from "./agent-studio.module.css";

const sections: Array<{ id: StudioSection; label: string; hint: string }> = [
  { id: "identity", label: "基本信息", hint: "边界与用途" },
  { id: "model", label: "模型", hint: "路由与能力" },
  { id: "prompt", label: "System Prompt", hint: "稳定行为契约" },
  { id: "orchestration", label: "协同编排", hint: "Lead + Sub Agents" },
  { id: "skills", label: "Skills", hint: "领域工作流" },
  { id: "capabilities", label: "Tools 与联网", hint: "确定性能力" },
  { id: "runtime", label: "运行与权限", hint: "隔离和审批" },
  { id: "evaluation", label: "测试与发布", hint: "质量门禁" },
];

const agentRows = [
  {
    id: "draft-public-opinion",
    name: "舆情研判 Agent",
    version: "0.2.0",
    status: "草稿",
    source: "浏览器草稿",
    active: true,
  },
  {
    id: "public-opinion-agent-0.1.1",
    name: "舆情研判 Agent",
    version: "0.1.1",
    status: "已发布",
    source: "本地 Bundle",
    active: false,
  },
  {
    id: "helper-agent-1.0.0",
    name: "通用调查助手",
    version: "1.0.0",
    status: "已发布",
    source: "本地 Bundle",
    active: false,
  },
  {
    id: "echo-agent-0.4.0",
    name: "工作区验证 Agent",
    version: "0.4.0",
    status: "已发布",
    source: "本地 Bundle",
    active: false,
  },
];

const lifecycleStages = [
  { id: "draft", label: "草稿", detail: "可编辑" },
  { id: "check", label: "预检", detail: "结构门禁" },
  { id: "preview", label: "隔离试跑", detail: "临时环境" },
  { id: "version", label: "版本", detail: "不可变 Bundle" },
  { id: "deploy", label: "部署", detail: "环境发布" },
] as const;

function riskLabel(risk: "low" | "medium" | "high") {
  return risk === "high" ? "高" : risk === "medium" ? "中" : "低";
}

export function AgentStudioWorkbench() {
  const [draft, setDraft] = useState<StudioDraft>(DEFAULT_STUDIO_DRAFT);
  const [activeSection, setActiveSection] =
    useState<StudioSection>("capabilities");
  const [agentQuery, setAgentQuery] = useState("");
  const [inspected, setInspected] = useState(false);
  const [notice, setNotice] = useState("草稿尚未保存到控制面");
  const contract = useMemo(() => evaluateStudioDraft(draft), [draft]);
  const filteredAgentRows = useMemo(() => {
    const query = agentQuery.trim().toLocaleLowerCase();
    if (!query) return agentRows;
    return agentRows.filter((agent) =>
      [agent.name, agent.version, agent.status, agent.source]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query),
    );
  }, [agentQuery]);

  useEffect(() => {
    const saved = window.localStorage.getItem("harness-agent-studio-draft");
    if (!saved) return;
    try {
      const recovered = restoreStudioDraft(JSON.parse(saved));
      if (recovered) {
        setDraft(recovered);
        setNotice("已兼容恢复浏览器草稿 · 尚未同步到控制面");
      }
    } catch {
      setNotice("浏览器草稿无法恢复，已使用仓库默认配置");
    }
  }, []);

  function updateDraft(update: Partial<StudioDraft>) {
    setDraft((current) => ({ ...current, ...update }));
    setInspected(false);
    setNotice("有尚未保存的修改");
  }

  function toggleBuiltin(tool: string) {
    updateDraft({
      builtinTools: draft.builtinTools.includes(tool)
        ? draft.builtinTools.filter((item) => item !== tool)
        : [...draft.builtinTools, tool],
    });
  }

  function toggleMcp(reference: string) {
    updateDraft({
      mcpServers: draft.mcpServers.includes(reference)
        ? draft.mcpServers.filter((item) => item !== reference)
        : [...draft.mcpServers, reference],
    });
  }

  function updateSubagent(index: number, update: Partial<StudioSubagent>) {
    updateDraft({
      subagents: draft.subagents.map((subagent, currentIndex) =>
        currentIndex === index ? { ...subagent, ...update } : subagent,
      ),
    });
  }

  function addSubagent() {
    if (draft.subagents.length >= 8) {
      setNotice("单个 Lead 最多绑定 8 个 Sub Agent");
      return;
    }
    const sequence = draft.subagents.length + 1;
    updateDraft({
      subagents: [
        ...draft.subagents,
        {
          alias: `specialist-${sequence}`,
          ref: "helper-agent@1.0.0",
          responsibility: "说明 Lead 应在什么情况下委派，以及 Sub Agent 必须返回什么。",
          background: true,
        },
      ],
      builtinTools: draft.builtinTools.includes("Task")
        ? draft.builtinTools
        : [...draft.builtinTools, "Task"],
      policy:
        draft.policy === "production-read-only"
          ? "production-orchestrator"
          : draft.policy,
    });
  }

  function removeSubagent(index: number) {
    const next = draft.subagents.filter(
      (_subagent, currentIndex) => currentIndex !== index,
    );
    updateDraft({
      subagents: next,
      builtinTools:
        next.length === 0
          ? draft.builtinTools.filter((tool) => tool !== "Task")
          : draft.builtinTools,
    });
  }

  function saveLocally() {
    window.localStorage.setItem("harness-agent-studio-draft", JSON.stringify(draft));
    setNotice("已保存浏览器草稿 · 接入认证后迁移到控制面");
  }

  function inspectDraft() {
    setInspected(true);
    setNotice(
      contract.ready
        ? "结构检查通过 · 发布部署前仍需校验 MCP 与 Sandbox 连通性"
        : `发现 ${contract.issues.length} 个阻塞问题`,
    );
  }

  function sectionSummary(section: StudioSection) {
    switch (section) {
      case "identity":
        return draft.name && draft.displayName ? "完整" : "待补充";
      case "model":
        return draft.model ? "已选择" : "待选择";
      case "prompt":
        return `${contract.promptSections}/5`;
      case "orchestration":
        return draft.subagents.length ? `${draft.subagents.length} 角色` : "单 Agent";
      case "skills":
        return `${draft.skills.length} 个`;
      case "capabilities":
        return `${contract.toolCount} 项`;
      case "runtime":
        return "平台锁定";
      case "evaluation":
        return `${draft.evalCases.length} 用例`;
    }
  }

  const selectedRoute =
    MODEL_ROUTES.find((route) => route.id === draft.modelRoute) ?? MODEL_ROUTES[0];
  const skill = draft.skills[0];
  const activeLifecycleStage = inspected && contract.ready ? "preview" : inspected ? "check" : "draft";
  const activeLifecycleIndex = lifecycleStages.findIndex(
    (stage) => stage.id === activeLifecycleStage,
  );

  return (
    <main className={styles.studioShell} data-studio-integration="pending-auth">
      <aside className={styles.agentRail} aria-label="Agent 列表">
        <div className={styles.studioBrand}>
          <span className={styles.brandMark} aria-hidden="true">
            H
          </span>
          <div>
            <strong>Agent Studio</strong>
            <span>Harness control plane</span>
          </div>
        </div>

        <nav className={styles.workspaceTabs} aria-label="工作区">
          <Link className={styles.workspaceTab} href="/">
            任务
          </Link>
          <Link
            className={styles.workspaceTabActive}
            href="/studio/agents"
            aria-current="page"
          >
            智能体
          </Link>
        </nav>

        <div className={styles.railHeading}>
          <span>智能体目录</span>
          <button
            type="button"
            aria-label="新建智能体"
            onClick={() => setNotice("新建流程将在 Studio API 接入后启用")}
          >
            +
          </button>
        </div>

        <label className={styles.agentSearch}>
          <span className={styles.visuallyHidden}>搜索智能体</span>
          <input
            type="search"
            value={agentQuery}
            onChange={(event) => setAgentQuery(event.target.value)}
            placeholder="搜索名称、版本或状态"
          />
          <kbd>{filteredAgentRows.length}</kbd>
        </label>

        <nav className={styles.agentList} aria-label="智能体草稿和版本">
          {filteredAgentRows.map((agent) => (
            <button
              type="button"
              key={agent.id}
              className={agent.active ? styles.agentRowActive : styles.agentRow}
              aria-current={agent.active ? "page" : undefined}
              onClick={() =>
                !agent.active && setNotice("版本切换将在列表 API 接入后启用")
              }
            >
              <span className={styles.agentMonogram} aria-hidden="true">
                {agent.name.slice(0, 1)}
              </span>
              <span className={styles.agentRowCopy}>
                <strong>{agent.name}</strong>
                <small>
                  {agent.version} · {agent.status} · {agent.source}
                </small>
              </span>
            </button>
          ))}
          {filteredAgentRows.length === 0 && (
            <div className={styles.agentListEmpty}>没有匹配的智能体</div>
          )}
        </nav>

        <div className={styles.railFooter}>
          <strong>本地目录</strong>
          <span>仅展示仓库内真实 Bundle；登录与目录 API 合并后切换为租户数据。</span>
        </div>
      </aside>

      <section className={styles.editorShell}>
        <header className={styles.editorHeader}>
          <div className={styles.titleBlock}>
            <div className={styles.eyebrow}>
              <span className={styles.draftDot} />
              草稿 · {draft.domain}
            </div>
            <div className={styles.titleLine}>
              <h1>{draft.displayName}</h1>
              <code>{draft.name}@{draft.version}</code>
            </div>
            <p>{draft.description}</p>
          </div>
          <div className={styles.headerActions}>
            <button type="button" className={styles.secondaryButton} onClick={saveLocally}>
              保存草稿
            </button>
            <button type="button" className={styles.checkButton} onClick={inspectDraft}>
              检查配置
            </button>
            <button
              type="button"
              className={styles.previewButton}
              disabled
              title="等待临时隔离环境 API 接入"
            >
              隔离试跑
            </button>
            <button
              type="button"
              className={styles.publishButton}
              disabled
              title="等待登录与 RBAC 分支接入"
            >
              发布
            </button>
          </div>
        </header>

        <ol className={styles.lifecycleBar} aria-label="从草稿到部署的生命周期">
          {lifecycleStages.map((stage, index) => {
            const state = index < activeLifecycleIndex
              ? "complete"
              : index === activeLifecycleIndex
                ? "active"
                : "pending";
            return (
              <li key={stage.id} data-state={state}>
                <span>{state === "complete" ? "✓" : index + 1}</span>
                <div>
                  <strong>{stage.label}</strong>
                  <small>{stage.detail}</small>
                </div>
              </li>
            );
          })}
        </ol>

        <div className={styles.editorBody}>
          <nav className={styles.sectionNav} aria-label="Agent 配置章节">
            {sections.map((section) => (
              <button
                type="button"
                key={section.id}
                className={activeSection === section.id ? styles.sectionActive : styles.sectionButton}
                onClick={() => setActiveSection(section.id)}
                aria-current={activeSection === section.id ? "step" : undefined}
              >
                <span>{section.label}</span>
                <span className={styles.sectionMeta}>
                  <small>{section.hint}</small>
                  <em>{sectionSummary(section.id)}</em>
                </span>
              </button>
            ))}
          </nav>

          <div className={styles.panelViewport}>
            {activeSection === "identity" && (
              <section className={styles.configPanel} aria-labelledby="identity-title">
                <PanelHeading
                  id="identity-title"
                  kicker="01 / Identity"
                  title="定义清楚它负责什么"
                  description="名称和边界会进入不可变 Agent 版本；不要把实现细节写进业务说明。"
                />
                <div className={styles.formGrid}>
                  <Field label="显示名称">
                    <input
                      value={draft.displayName}
                      onChange={(event) => updateDraft({ displayName: event.target.value })}
                    />
                  </Field>
                  <Field label="Agent ID" hint="发布后不可原地修改">
                    <input
                      className={styles.monoInput}
                      value={draft.name}
                      onChange={(event) => updateDraft({ name: event.target.value })}
                    />
                  </Field>
                  <Field label="业务领域">
                    <input
                      className={styles.monoInput}
                      value={draft.domain}
                      onChange={(event) => updateDraft({ domain: event.target.value })}
                    />
                  </Field>
                  <Field label="版本">
                    <input
                      className={styles.monoInput}
                      value={draft.version}
                      onChange={(event) => updateDraft({ version: event.target.value })}
                    />
                  </Field>
                  <Field label="场景说明" wide>
                    <textarea
                      rows={3}
                      value={draft.description}
                      onChange={(event) => updateDraft({ description: event.target.value })}
                    />
                  </Field>
                </div>
              </section>
            )}

            {activeSection === "model" && (
              <section className={styles.configPanel} aria-labelledby="model-title">
                <PanelHeading
                  id="model-title"
                  kicker="02 / Model"
                  title="选择经过平台验证的模型路由"
                  description="Agent 只引用路由和模型；Endpoint 与凭据始终由平台托管。"
                />
                <div className={styles.routeCards}>
                  {MODEL_ROUTES.map((route) => (
                    <button
                      type="button"
                      key={route.id}
                      className={draft.modelRoute === route.id ? styles.routeCardActive : styles.routeCard}
                      onClick={() =>
                        updateDraft({ modelRoute: route.id, model: route.models[0] })
                      }
                    >
                      <span className={styles.routeProvider}>{route.provider}</span>
                      <strong>{route.label}</strong>
                      <small>{route.capabilities.join(" · ")}</small>
                    </button>
                  ))}
                </div>
                <div className={styles.formGridSingle}>
                  <Field label="执行模型">
                    <select
                      value={draft.model}
                      onChange={(event) => updateDraft({ model: event.target.value })}
                    >
                      {selectedRoute.models.map((model) => (
                        <option key={model} value={model}>{model}</option>
                      ))}
                    </select>
                  </Field>
                </div>
                <InfoStrip tone="neutral">
                  模型目录只展示已完成 Anthropic-compatible、流式输出和工具调用验证的组合。
                </InfoStrip>
              </section>
            )}

            {activeSection === "prompt" && (
              <section className={styles.configPanel} aria-labelledby="prompt-title">
                <PanelHeading
                  id="prompt-title"
                  kicker="03 / System Prompt"
                  title="写稳定行为契约，不堆易变知识"
                  description="生产门禁要求五个章节。业务 SOP 放入 Skills，确定性约束留给 Tools 和 Policy。"
                />
                <div className={styles.promptChecklist}>
                  {REQUIRED_PROMPT_HEADINGS.map((heading) => (
                    <span
                      key={heading}
                      className={draft.systemPrompt.includes(heading) ? styles.checkPresent : styles.checkMissing}
                    >
                      {draft.systemPrompt.includes(heading) ? "✓" : "·"} {heading.replace("## ", "")}
                    </span>
                  ))}
                </div>
                <textarea
                  className={styles.codeEditor}
                  aria-label="System Prompt"
                  spellCheck={false}
                  value={draft.systemPrompt}
                  onChange={(event) => updateDraft({ systemPrompt: event.target.value })}
                />
              </section>
            )}

            {activeSection === "orchestration" && (
              <section className={styles.configPanel} aria-labelledby="orchestration-title">
                <PanelHeading
                  id="orchestration-title"
                  kicker="04 / Collaboration"
                  title="让 Lead 负责决策，让专家并行取证"
                  description="Lead 是唯一面向用户的主线；Sub Agent 使用固定版本、独立职责和自己的权限上限，通过 Task 返回可验收结果。"
                />

                <div className={styles.orchestrationSummary} aria-label="协同运行摘要">
                  <div><span>前台主线</span><strong>1 Lead</strong></div>
                  <div><span>后台并行</span><strong>{contract.backgroundSubagentCount} Sub</strong></div>
                  <div>
                    <span>串行等待</span>
                    <strong>{contract.subagentCount - contract.backgroundSubagentCount} Sub</strong>
                  </div>
                  <div><span>委派入口</span><strong>Task · 受策略约束</strong></div>
                </div>

                <div className={styles.orchestrationGraph} aria-label="多智能体协同拓扑">
                  <article className={styles.leadAgentCard}>
                    <span className={styles.agentRoleBadge}>LEAD</span>
                    <div className={styles.agentIdentityMark} aria-hidden="true">L</div>
                    <div>
                      <strong>{draft.displayName}</strong>
                      <code>{draft.name}@{draft.version}</code>
                      <p>拆解任务、选择专家、交叉验证并汇总最终回答。</p>
                    </div>
                    <span className={styles.agentModeBadge}>前台主线</span>
                  </article>

                  {draft.subagents.length > 0 ? (
                    <>
                      <div className={styles.orchestrationFanout} aria-hidden="true">
                        <i />
                      </div>
                      <div className={styles.subagentTopology}>
                        {draft.subagents.map((subagent, index) => (
                          <article className={styles.subagentNode} key={`${subagent.alias}-${index}`}>
                            <div className={styles.subagentNodeHeader}>
                              <span className={styles.agentIdentityMark} aria-hidden="true">
                                {index + 1}
                              </span>
                              <span data-background={subagent.background}>
                                {subagent.background ? "并行" : "等待"}
                              </span>
                            </div>
                            <strong className={styles.subagentNodeName}>
                              {subagent.alias || "未命名角色"}
                            </strong>
                            <code className={styles.subagentNodeRef}>
                              {subagent.ref || "未固定版本"}
                            </code>
                            <p>{subagent.responsibility || "尚未定义职责"}</p>
                          </article>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className={styles.orchestrationEmpty}>
                      <strong>当前为单 Agent</strong>
                      <span>添加已发布的 Sub Agent 后，Lead 才能使用 Task 委派。</span>
                    </div>
                  )}
                </div>

                <div className={styles.groupHeading}>
                  <div>
                    <h3>角色绑定</h3>
                    <p>角色别名用于 Lead 选择专家；同一通用 Agent 版本可绑定多个职责。</p>
                  </div>
                  <button type="button" className={styles.addSubagentButton} onClick={addSubagent}>
                    + 添加 Sub Agent
                  </button>
                </div>

                <div className={styles.subagentEditors}>
                  {draft.subagents.map((subagent, index) => {
                    const catalogAgent = PUBLISHED_SUBAGENTS.find(
                      (agent) => agent.ref === subagent.ref,
                    );
                    return (
                    <article className={styles.subagentEditor} key={`${subagent.alias}-editor-${index}`}>
                      <header>
                        <div>
                          <span>SUB {String(index + 1).padStart(2, "0")}</span>
                          <strong>{subagent.alias || "未命名角色"}</strong>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeSubagent(index)}
                          aria-label={`移除 ${subagent.alias || `Sub Agent ${index + 1}`}`}
                        >
                          移除
                        </button>
                      </header>
                      <div className={styles.formGrid}>
                        <Field label="角色别名" hint="Lead 调用名称">
                          <input
                            className={styles.monoInput}
                            value={subagent.alias}
                            onChange={(event) => updateSubagent(index, { alias: event.target.value })}
                          />
                        </Field>
                        <Field label="固定版本引用" hint="从已发布目录选择">
                          <select
                            className={styles.monoInput}
                            value={subagent.ref}
                            onChange={(event) => updateSubagent(index, { ref: event.target.value })}
                          >
                            {!PUBLISHED_SUBAGENTS.some((agent) => agent.ref === subagent.ref) && (
                              <option value={subagent.ref}>{subagent.ref || "未识别版本"}</option>
                            )}
                            {PUBLISHED_SUBAGENTS.map((agent) => (
                              <option key={agent.ref} value={agent.ref}>
                                {agent.label} · {agent.ref}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <Field label="职责与返回契约" wide>
                          <textarea
                            rows={3}
                            value={subagent.responsibility}
                            onChange={(event) =>
                              updateSubagent(index, { responsibility: event.target.value })
                            }
                          />
                        </Field>
                      </div>
                      {catalogAgent && (
                        <div className={styles.catalogBinding}>
                          <span data-status={catalogAgent.status}>
                            {catalogAgent.status === "approved" ? "目录已审批" : "目录已弃用"}
                          </span>
                          <div>
                            <strong>{catalogAgent.label}</strong>
                            <small>{catalogAgent.description}</small>
                          </div>
                          <code>{catalogAgent.policy} · {catalogAgent.tools.join(" / ")}</code>
                        </div>
                      )}
                      <label className={styles.backgroundMode}>
                        <input
                          type="checkbox"
                          checked={subagent.background}
                          onChange={(event) =>
                            updateSubagent(index, { background: event.target.checked })
                          }
                        />
                        <span aria-hidden="true"><i /></span>
                        <div>
                          <strong>允许后台并行</strong>
                          <small>Lead 可同时派出多个独立任务；结果仍必须由 Lead 验收后汇总。</small>
                        </div>
                      </label>
                    </article>
                    );
                  })}
                </div>

                <InfoStrip tone="neutral">
                  每个 Sub Agent 继承自己的 Prompt、Skills、Builtin Tools、Policy 和轮次上限。当前运行时不向 Sub Agent 注入 MCP 或 Python Tool；需要联网的证据先由 Lead 收集到共享沙箱。
                </InfoStrip>
              </section>
            )}

            {activeSection === "skills" && skill && (
              <section className={styles.configPanel} aria-labelledby="skills-title">
                <PanelHeading
                  id="skills-title"
                  kicker="05 / Skills"
                  title="沉淀可复用的领域工作流"
                  description="发布时 Skill 及 references、scripts、assets 会一同进入不可变快照。"
                />
                <div className={styles.skillHeader}>
                  <span className={styles.skillGlyph} aria-hidden="true">S</span>
                  <div>
                    <strong>{skill.name}</strong>
                    <span>Agent 内置 Skill · 随版本发布</span>
                  </div>
                  <button type="button" onClick={() => setNotice("Skill 模板库将在目录 API 接入后启用")}>从模板添加</button>
                </div>
                <div className={styles.formGridSingle}>
                  <Field label="Skill 描述">
                    <input
                      value={skill.description}
                      onChange={(event) =>
                        updateDraft({
                          skills: [{ ...skill, description: event.target.value }],
                        })
                      }
                    />
                  </Field>
                  <Field label="工作流说明">
                    <textarea
                      rows={10}
                      value={skill.instructions}
                      onChange={(event) =>
                        updateDraft({
                          skills: [{ ...skill, instructions: event.target.value }],
                        })
                      }
                    />
                  </Field>
                </div>
              </section>
            )}

            {activeSection === "capabilities" && (
              <section className={styles.configPanel} aria-labelledby="capabilities-title">
                <PanelHeading
                  id="capabilities-title"
                  kicker="06 / Capabilities"
                  title="只授予完成场景所需的能力"
                  description="能力是显式上限。没有选择的工具不会在运行时注入。"
                />

                <div className={styles.groupHeading}>
                  <div>
                    <h3>工作区工具</h3>
                    <p>实际在强制隔离的 Sandbox 中执行。</p>
                  </div>
                  <span>{draft.builtinTools.length} 项已启用</span>
                </div>
                <div className={styles.toolGrid}>
                  {BUILTIN_TOOLS.map((tool) => {
                    const enabled = draft.builtinTools.includes(tool.id);
                    return (
                      <label key={tool.id} className={enabled ? styles.toolCardEnabled : styles.toolCard}>
                        <input
                          type="checkbox"
                          checked={enabled}
                          onChange={() => toggleBuiltin(tool.id)}
                        />
                        <span className={styles.toolCheck} aria-hidden="true">{enabled ? "✓" : ""}</span>
                        <span className={styles.toolCopy}>
                          <strong>{tool.label}</strong>
                          <small>{tool.description}</small>
                          <em data-risk={tool.risk}>{tool.approval}</em>
                        </span>
                        <code>{tool.id}</code>
                      </label>
                    );
                  })}
                </div>

                <div className={styles.groupHeading}>
                  <div>
                    <h3>数据与联网能力</h3>
                    <p>通过平台注册的逻辑 MCP，不接受任意 URL 或内联密钥。</p>
                  </div>
                  <span>{draft.mcpServers.length} 项已启用</span>
                </div>
                {MCP_OPTIONS.map((mcp) => {
                  const enabled = draft.mcpServers.includes(mcp.id);
                  return (
                    <label key={mcp.id} className={enabled ? styles.mcpCardEnabled : styles.mcpCard}>
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={() => toggleMcp(mcp.id)}
                      />
                      <span className={styles.mcpSignal} aria-hidden="true"><i /><i /><i /></span>
                      <span className={styles.mcpCopy}>
                        <span className={styles.mcpTitleLine}>
                          <strong>{mcp.label}</strong>
                          <span>只读</span>
                          <span>外部服务</span>
                        </span>
                        <small>{mcp.description}</small>
                        <code>{mcp.tools.join(" · ")}</code>
                      </span>
                      <span className={styles.switchVisual} aria-hidden="true"><i /></span>
                    </label>
                  );
                })}
                {draft.mcpServers.includes("tavily-readonly") && (
                  <InfoStrip tone="warning">
                    检索词和待抽取 URL 会发送给 Tavily。发布部署前必须从实际 Sandbox 检查凭据、MCP tools/list 与公网可达性；这不会开放任意 Bash 网络访问。
                  </InfoStrip>
                )}
              </section>
            )}

            {activeSection === "runtime" && (
              <section className={styles.configPanel} aria-labelledby="runtime-title">
                <PanelHeading
                  id="runtime-title"
                  kicker="07 / Runtime"
                  title="隔离是生产基线，不是 Agent 开关"
                  description="构建者声明能力，平台把执行档位绑定到 Daytona、gVisor 或其他安全后端。"
                />
                <div className={styles.isolationCard}>
                  <span className={styles.isolationGlyph} aria-hidden="true"><i /><i /></span>
                  <div>
                    <strong>隔离执行 · 平台托管</strong>
                    <p>工作区、进程、网络和生命周期由部署环境统一约束。</p>
                  </div>
                  <span className={styles.lockedBadge}>生产强制</span>
                </div>
                <div className={styles.runtimeAssurances}>
                  <article className={styles.identityBoundary}>
                    <header>
                      <div><span>IDENTITY</span><strong>独立工作负载身份</strong></div>
                      <em>发布时生成</em>
                    </header>
                    <dl>
                      <div><dt>主体</dt><dd>agent:{draft.name}@{draft.version}</dd></div>
                      <div><dt>入站</dt><dd>继承已认证用户与租户上下文</dd></div>
                      <div><dt>出站</dt><dd>按 Tool / MCP 单独注入运行时凭据</dd></div>
                    </dl>
                  </article>
                  <article className={styles.continuityBoundary}>
                    <header>
                      <div><span>CONTINUITY</span><strong>恢复与归档语义</strong></div>
                      <em>显式配置</em>
                    </header>
                    <label>
                      <input
                        type="checkbox"
                        checked={draft.restoreSession}
                        onChange={(event) => updateDraft({ restoreSession: event.target.checked })}
                      />
                      <span>恢复同一会话的 SDK 上下文</span>
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={draft.archiveOnComplete}
                        onChange={(event) => updateDraft({ archiveOnComplete: event.target.checked })}
                      />
                      <span>运行结束后归档沙箱工作区</span>
                    </label>
                    <p>当前保障会话与审批恢复；不宣称支持任意工具步骤的持久化 checkpoint。</p>
                  </article>
                </div>
                <div className={styles.formGrid}>
                  <Field label="权限 Profile" wide>
                    <select
                      value={draft.policy}
                      onChange={(event) => updateDraft({ policy: event.target.value })}
                    >
                      {POLICY_OPTIONS.map((policy) => (
                        <option key={policy.id} value={policy.id}>
                          {policy.label} · {policy.description}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="最大轮次">
                    <input
                      type="number"
                      min={1}
                      value={draft.maxTurns}
                      onChange={(event) => updateDraft({ maxTurns: Number(event.target.value) })}
                    />
                  </Field>
                  <Field label="超时（秒）">
                    <input
                      type="number"
                      min={1}
                      value={draft.timeoutSeconds}
                      onChange={(event) => updateDraft({ timeoutSeconds: Number(event.target.value) })}
                    />
                  </Field>
                  <Field label="单次预算（USD）">
                    <input
                      type="number"
                      min={0.01}
                      step={0.1}
                      value={draft.maxBudgetUsd}
                      onChange={(event) => updateDraft({ maxBudgetUsd: Number(event.target.value) })}
                    />
                  </Field>
                </div>
              </section>
            )}

            {activeSection === "evaluation" && (
              <section className={styles.configPanel} aria-labelledby="evaluation-title">
                <PanelHeading
                  id="evaluation-title"
                  kicker="08 / Quality gate"
                  title="用真实失败路径证明它可以发布"
                  description="结构检查只是第一层；上线前仍要在固定版本和真实 Sandbox 中跑 live eval。"
                />
                <div className={styles.evalList}>
                  {draft.evalCases.map((testCase) => (
                    <article key={testCase.id} className={styles.evalCase}>
                      <span data-tag={testCase.tag}>{testCase.tag}</span>
                      <div>
                        <strong>{testCase.label}</strong>
                        <p>{testCase.prompt}</p>
                        <div className={styles.evalAssertions}>
                          <span>终态 {testCase.expect.terminalStatuses.join(" / ")}</span>
                          {testCase.expect.requiredTools.length > 0 && (
                            <span>必须调用 {testCase.expect.requiredTools.join(" / ")}</span>
                          )}
                          {testCase.expect.forbiddenTools.length > 0 && (
                            <span>禁止 {testCase.expect.forbiddenTools.join(" / ")}</span>
                          )}
                          {testCase.expect.outputContains.length > 0 && (
                            <span>输出含 {testCase.expect.outputContains.join(" / ")}</span>
                          )}
                          {testCase.expect.approvalRequired && <span>必须经过审批</span>}
                          <span>≤ {testCase.expect.maxDurationSeconds}s</span>
                        </div>
                      </div>
                      <code>{testCase.id}</code>
                    </article>
                  ))}
                </div>
                <div className={styles.releaseGate}>
                  <div>
                    <span>本地结构门禁</span>
                    <strong>{contract.ready ? "可生成发布包" : "存在阻塞问题"}</strong>
                  </div>
                  <div>
                    <span>真实环境预检</span>
                    <strong>等待 MCP / Sandbox 连通性验证</strong>
                  </div>
                  <div>
                    <span>离线轨迹评测</span>
                    <strong>{draft.evalCases.length} 用例 · 工具 / 终态 / 输出断言</strong>
                  </div>
                  <div>
                    <span>线上质量监控</span>
                    <strong>待接入 Langfuse Dataset / Score / Alert</strong>
                  </div>
                </div>
                <div className={styles.releaseArchitecture} aria-label="发布架构">
                  <article>
                    <span>PREVIEW</span>
                    <strong>临时隔离环境</strong>
                    <p>结构检查通过后创建短时试跑环境；失败不污染任何正式版本。</p>
                    <code>TTL 60 min · 待控制面接入</code>
                  </article>
                  <article>
                    <span>VERSION</span>
                    <strong>不可变 Bundle</strong>
                    <p>Prompt、Skills、Tools、Sub Agent 固定引用和策略一次性快照。</p>
                    <code>{draft.name}@{draft.version}</code>
                  </article>
                  <article>
                    <span>ENVIRONMENT</span>
                    <strong>按环境晋级</strong>
                    <p>测试、灰度、生产只切换版本指针；保留历史以支持快速回退。</p>
                    <code>test → canary → production</code>
                  </article>
                </div>
              </section>
            )}
          </div>
        </div>

        <footer className={styles.editorFooter}>
          <span className={notice.includes("阻塞") ? styles.noticeError : styles.noticeDot} aria-hidden="true" />
          <span>{notice}</span>
          <code>revision 7</code>
        </footer>
      </section>

      <aside className={styles.contractRail} aria-label="有效运行契约">
        <div className={styles.contractHeader}>
          <div>
            <span>有效运行契约</span>
            <strong>{contract.ready ? "结构就绪" : "需要处理"}</strong>
          </div>
          <span className={styles.riskBadge} data-risk={contract.risk}>
            风险 {riskLabel(contract.risk)}
          </span>
        </div>

        <div className={styles.capabilitySpine}>
          <ContractNode
            index="M"
            label="Model"
            value={contract.model}
            detail={contract.routeLabel}
            state="ready"
          />
          <ContractNode
            index="P"
            label="Prompt"
            value={`${contract.promptSections} / 5 章节`}
            detail="稳定行为契约"
            state={contract.promptSections === 5 ? "ready" : "error"}
          />
          <ContractNode
            index="S"
            label="Skills"
            value={`${contract.skillCount} 个领域工作流`}
            detail={draft.skills.map((item) => item.name).join(", ")}
            state={contract.skillCount > 0 ? "ready" : "error"}
          />
          <ContractNode
            index="T"
            label="Tools"
            value={`${contract.toolCount} 项能力`}
            detail={`${contract.networkLabel} · ${contract.approvalLabel}`}
            state="ready"
          />
          <ContractNode
            index="A"
            label="Agents"
            value={contract.collaborationLabel}
            detail={
              contract.subagentCount > 0
                ? `${contract.backgroundSubagentCount} 个角色允许后台并行`
                : "未启用 Task 委派"
            }
            state={
              draft.builtinTools.includes("Task") === (contract.subagentCount > 0)
                ? "ready"
                : "error"
            }
          />
          <ContractNode
            index="I"
            label="Isolation"
            value={contract.sandboxLabel}
            detail="独立身份 · Provider 由执行档位决定"
            state="locked"
          />
          <ContractNode
            index="R"
            label="Release"
            value={contract.ready ? "可生成不可变 Bundle" : "配置未通过"}
            detail="发布后版本不可覆盖"
            state={contract.ready ? "ready" : "error"}
          />
        </div>

        <section className={styles.contractFacts}>
          <h2>边界摘要</h2>
          <dl>
            <div><dt>联网</dt><dd>{contract.networkLabel}</dd></div>
            <div><dt>文件</dt><dd>{draft.builtinTools.includes("Write") ? "可在沙箱生成" : "只读"}</dd></div>
            <div><dt>命令</dt><dd>{draft.builtinTools.includes("Bash") ? "启用 · 默认审批" : "未启用"}</dd></div>
            <div>
              <dt>协同</dt>
              <dd>{contract.collaborationLabel}</dd>
            </div>
            <div>
              <dt>Sub 角色</dt>
              <dd>
                {draft.subagents.length
                  ? draft.subagents.map((subagent) => subagent.alias).join(", ")
                  : "无"}
              </dd>
            </div>
            <div><dt>会话</dt><dd>{draft.restoreSession ? "允许恢复" : "每轮新建"}</dd></div>
            <div><dt>归档</dt><dd>{draft.archiveOnComplete ? "运行结束归档" : "按 TTL 回收"}</dd></div>
            <div><dt>身份</dt><dd>发布版本独立工作负载身份</dd></div>
            <div><dt>预算</dt><dd>${draft.maxBudgetUsd.toFixed(2)} / Run</dd></div>
          </dl>
        </section>

        {inspected && (
          <section className={contract.ready ? styles.validationReady : styles.validationIssues} role="status">
            <strong>{contract.ready ? "结构检查通过" : "发布被阻止"}</strong>
            {contract.ready ? (
              <p>Manifest、Prompt、Skills、工具与评测覆盖满足本地编译前条件。</p>
            ) : (
              <ul>{contract.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
            )}
          </section>
        )}

        <p className={styles.contractFootnote}>
          页面不保存 Endpoint、Token 或任意 MCP URL。凭据只在运行时按租户与执行身份注入。
        </p>
      </aside>
    </main>
  );
}

function PanelHeading({
  id,
  kicker,
  title,
  description,
}: {
  id: string;
  kicker: string;
  title: string;
  description: string;
}) {
  return (
    <header className={styles.panelHeading}>
      <span>{kicker}</span>
      <h2 id={id}>{title}</h2>
      <p>{description}</p>
    </header>
  );
}

function Field({
  label,
  hint,
  wide = false,
  children,
}: {
  label: string;
  hint?: string;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className={wide ? styles.fieldWide : styles.field}>
      <span>{label}{hint && <small>{hint}</small>}</span>
      {children}
    </label>
  );
}

function InfoStrip({
  tone,
  children,
}: {
  tone: "neutral" | "warning";
  children: React.ReactNode;
}) {
  return <div className={tone === "warning" ? styles.warningStrip : styles.infoStrip}>{children}</div>;
}

function ContractNode({
  index,
  label,
  value,
  detail,
  state,
}: {
  index: string;
  label: string;
  value: string;
  detail: string;
  state: "ready" | "error" | "locked";
}) {
  return (
    <div className={styles.contractNode} data-state={state}>
      <span className={styles.nodeIndex}>{index}</span>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}
