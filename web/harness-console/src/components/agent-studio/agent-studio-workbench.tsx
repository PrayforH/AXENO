"use client";

import { useMemo, useState } from "react";
import {
  BUILTIN_TOOLS,
  DEFAULT_STUDIO_DRAFT,
  MCP_OPTIONS,
  MODEL_ROUTES,
  POLICY_OPTIONS,
  REQUIRED_PROMPT_HEADINGS,
  evaluateStudioDraft,
  type StudioDraft,
  type StudioSection,
} from "../../lib/agent-studio";
import styles from "./agent-studio.module.css";

const sections: Array<{ id: StudioSection; label: string; hint: string }> = [
  { id: "identity", label: "基本信息", hint: "边界与用途" },
  { id: "model", label: "模型", hint: "路由与能力" },
  { id: "prompt", label: "System Prompt", hint: "稳定行为契约" },
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
    active: true,
  },
  {
    id: "contract-reviewer",
    name: "合同审查助手",
    version: "0.1.0",
    status: "已发布",
    active: false,
  },
  {
    id: "ticket-assistant",
    name: "工单分诊助手",
    version: "0.3.1",
    status: "已发布",
    active: false,
  },
];

function riskLabel(risk: "low" | "medium" | "high") {
  return risk === "high" ? "高" : risk === "medium" ? "中" : "低";
}

export function AgentStudioWorkbench() {
  const [draft, setDraft] = useState<StudioDraft>(DEFAULT_STUDIO_DRAFT);
  const [activeSection, setActiveSection] =
    useState<StudioSection>("capabilities");
  const [inspected, setInspected] = useState(false);
  const [notice, setNotice] = useState("草稿尚未保存到控制面");
  const contract = useMemo(() => evaluateStudioDraft(draft), [draft]);

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

  const selectedRoute =
    MODEL_ROUTES.find((route) => route.id === draft.modelRoute) ?? MODEL_ROUTES[0];
  const skill = draft.skills[0];

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

        <div className={styles.railHeading}>
          <span>智能体</span>
          <button
            type="button"
            aria-label="新建智能体"
            onClick={() => setNotice("新建流程将在 Studio API 接入后启用")}
          >
            +
          </button>
        </div>

        <nav className={styles.agentList} aria-label="智能体草稿和版本">
          {agentRows.map((agent) => (
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
                  {agent.version} · {agent.status}
                </small>
              </span>
            </button>
          ))}
        </nav>

        <div className={styles.railFooter}>
          <a href="/">返回任务工作台</a>
          <span>Studio 发布需要 Builder 权限</span>
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
              className={styles.publishButton}
              disabled
              title="等待登录与 RBAC 分支接入"
            >
              发布
            </button>
          </div>
        </header>

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
                <small>{section.hint}</small>
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

            {activeSection === "skills" && skill && (
              <section className={styles.configPanel} aria-labelledby="skills-title">
                <PanelHeading
                  id="skills-title"
                  kicker="04 / Skills"
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
                  kicker="05 / Capabilities"
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
                  kicker="06 / Runtime"
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
                  kicker="07 / Quality gate"
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
                    <span>部署前检查</span>
                    <strong>等待 MCP / Sandbox 预检</strong>
                  </div>
                  <div>
                    <span>发布权限</span>
                    <strong>等待登录与 RBAC 接入</strong>
                  </div>
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
            index="I"
            label="Isolation"
            value={contract.sandboxLabel}
            detail="Provider 由平台执行档位决定"
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
            <div><dt>子 Agent</dt><dd>{draft.subagents.length ? draft.subagents.join(", ") : "无"}</dd></div>
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
