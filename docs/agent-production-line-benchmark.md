# Agent production line benchmark

This note records the design decisions taken from current commercial and open-source Agent platforms. The target remains a Claude Agent SDK harness, not a generic graph builder.

## What a production line must cover

An Agent production line is complete only when it connects four planes:

1. **Definition plane** — immutable Agent identity, model route, prompt, Skills, Tools, MCP bindings, subagents, policy and evaluation suite.
2. **Quality plane** — static validation, real-sandbox preflight, offline trajectory evaluation and sampled online evaluation.
3. **Runtime plane** — authenticated workload identity, isolated workspace, resumable approvals, bounded execution and explicit session semantics.
4. **Operations plane** — immutable versions, environment promotion, rollback, traces, scores, alerts and audit history.

A visual workflow editor is useful, but it is not a production line by itself.

## Patterns worth adopting

| Reference | Strongest production pattern | Harness decision |
| --- | --- | --- |
| NAC | Drafts, temporary test lanes, immutable versions, environment promotion, rollback and deployment snapshots form one lifecycle. | Keep the lifecycle, but make the next gate visible and recover from page failures instead of presenting a blank workspace. |
| OpenAI Agents SDK | A manager can keep ownership while invoking specialists as tools; handoff is a different ownership model. Sessions, guardrails, approvals and traces are first-class. | Current `Lead + Sub` uses manager ownership. Do not present handoff until the runtime and UI can represent the ownership change correctly. |
| Google ADK / Agent Platform | Agent Registry, Skill Registry, workload identity, sessions, Memory Bank, sandbox templates, revisions/traffic and offline/online evaluation are separate managed resources. | Bind only approved, version-pinned resources. Keep identity, memory, sandbox and evaluation visible in the effective contract. |
| Microsoft Agent Framework | Workflow state is isolated per execution. Checkpoints persist executor state, pending messages, requests and shared state, and can resume after failure or migration. | Distinguish SDK session restore from durable step checkpoints. The current harness guarantees the former, not arbitrary tool-step recovery. |
| AWS Bedrock AgentCore | Runtime, Memory, Gateway, Identity, Registry, sandbox tools, Observability and Evaluations are modular and framework/model agnostic. | Keep Claude SDK as the loop while treating runtime, credentials, sandbox, registry and observability as replaceable platform adapters. |
| LangGraph / LangSmith | Durable execution, persistence, human interrupts and time travel belong in the orchestration runtime; traces and evaluation belong in an operations platform. | Add a durable outer workflow only for long-running business processes. Do not replace the SDK loop for ordinary tool-using Agents. |
| Dify / Coze Studio / Flowise | Low-code authoring, prompt/model comparison, resource marketplaces, RAG pipelines, visual debugging and API publication shorten prototyping. | Provide curated catalogs and progressively disclosed forms. Avoid an unrestricted node canvas and avoid leaking secrets or arbitrary MCP URLs into drafts. |
| CrewAI | Autonomous Crews and deterministic, event-driven Flows solve different problems and can be combined. | Keep specialist collaboration inside one run; use deterministic workflows around the run for business state transitions and retries. |
| AgentScope | Agent-as-a-Service, streaming APIs, interrupt service, sandbox adapters and local/serverless/Kubernetes deployment reduce the gap between development and production. | Preserve one runtime contract across local, Daytona and future gVisor/Kubernetes backends; expose cancellation and sandbox facts consistently. |

## Current multi-agent contract

The current implementation intentionally supports one collaboration shape:

```text
User
  |
  v
Lead Agent (owns the conversation and final answer)
  |-- Task -> evidence-researcher  [background]
  |-- Task -> risk-reviewer        [background]
  `-- Task -> quality-reviewer     [foreground]
```

- A role alias is distinct from an Agent artifact. The same immutable `helper-agent@1.0.0` can be bound more than once with different responsibilities.
- Every role has its own prompt, Skills, builtin tool allowlist, policy and turn limit.
- The SDK `Task` tool is the only delegation entrance. Unknown subagent identities fail closed.
- A subagent policy is evaluated independently by the Harness tool gate.
- The Lead remains responsible for cross-checking and the final user-facing result.
- Nested delegation, subagent MCP/Python tools and conversation handoff are not enabled.

## Release gates

The recommended CI/CD path is:

```text
editable draft
  -> schema and package validation
  -> real sandbox / MCP preflight
  -> offline trajectory evals
  -> temporary isolated preview
  -> immutable signed bundle
  -> test environment
  -> canary environment
  -> production environment
  -> sampled online evaluation and alerts
```

Each offline evaluation should assert more than output text:

- allowed terminal statuses;
- required and forbidden tools;
- whether approval must occur;
- required output evidence;
- maximum duration;
- later: maximum tokens/cost and subagent trajectory assertions.

Production promotion should use the same content hash that passed the gates. Environment configuration may be injected at deployment time, but it must be captured in a deployment snapshot without exposing secrets.

## Deliberately deferred

These capabilities are valuable but should not be represented as working before their contracts exist:

- durable checkpoints between arbitrary SDK/tool steps;
- agent-to-agent conversation ownership handoff;
- nested multi-agent graphs;
- direct editing of raw credentials or arbitrary MCP endpoints;
- online evaluation and automatic rollback based only on an LLM judge;
- a general-purpose node canvas for every Agent.

## Primary references

- [OpenAI Agents SDK guide](https://developers.openai.com/api/docs/guides/agents)
- [Google Agent Development Kit](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk)
- [Microsoft Agent Framework checkpoints](https://learn.microsoft.com/en-us/agent-framework/workflows/checkpoints)
- [Amazon Bedrock AgentCore overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [Dify](https://github.com/langgenius/dify)
- [Coze Studio](https://github.com/coze-dev/coze-studio)
- [Flowise](https://docs.flowiseai.com/)
- [CrewAI](https://github.com/crewAIInc/crewAI)
- [AgentScope](https://github.com/agentscope-ai/agentscope)
