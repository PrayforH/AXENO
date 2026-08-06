# General Agent and Codex Workbench Design

**Date:** 2026-07-13

**Status:** Approved

## Goal

Turn the current Claude Agent SDK harness into a reusable general-agent foundation that can safely search the web, delegate bounded work to helper agents, request human approval without deadlocking, and present long executions in a compact Codex-style workbench.

## Why this matters

The harness already provides useful infrastructure—Agent Manifests, sandboxing, durable events, approvals, AG-UI transport, Assistant UI rendering, artifacts, memory, and Langfuse export—but those pieces are not yet assembled into a convincing general agent product. The current echo agent cannot use the web or delegate. The UI exposes raw execution detail instead of helping the user understand and control a run. Approval rejection can also leave the client in a non-terminal state.

This change creates a stable foundation for future domain agents:

- Domain agents opt into reviewed capabilities through a declarative Manifest instead of reimplementing tool wiring.
- Server-owned MCP registration separates public agent definitions from credentials and deployment details.
- Durable task, tool, approval, and run events become the single source of truth for both UI and observability.
- A compact execution ribbon keeps normal conversations readable while preserving full inspection when needed.
- The same approval and sandbox contract applies to the general agent and future specialized agents.

## Priorities

### P0: implement now

1. Tavily search and extract through a server-owned, read-only MCP registration.
2. A real helper subagent referenced by the general agent Manifest.
3. Correct approval lifecycle for approve and reject, including useful request context.
4. One durable run-state projection shared by activity, approvals, tool cards, and composer state.
5. A one-line execution ribbon that expands into a task and tool tree.
6. Multi-task grouping by task identity and parent tool identity.
7. Treat web results as untrusted content and render source metadata clearly.
8. Tighten the full-page layout and remove the decorative `LIVE` rail.

### P1: next

- Conversation history and durable thread body restoration.
- Structured plans, user steering, and editable task queues.
- Memory inspection, editing, and deletion.
- MCP/connector management and user credential authorization.
- Unified source, diff, artifact, and web-preview cards.
- Retry, provider fallback, rate limits, budgets, and session-scoped approval rules.
- Langfuse deep links and token/cost summaries.

### P2: later

- Browser/computer use.
- Automations, background agents, and notifications.
- Evaluation/control-plane workflows and version release gates.
- Team sharing, replay, comments, and collaborative approval.

## Architecture

```text
Agent Manifest
  ├─ builtin tools
  ├─ mcp: tavily-readonly
  └─ subagents: helper-agent@1.0.0
       │
       ▼
Server-owned Tool Registry
  ├─ Tavily remote MCP URL
  ├─ dynamic Authorization header
  ├─ exact allowed-tool list
  └─ credential redaction
       │
       ▼
Claude Agent SDK + sandbox + policy gate
       │
       ▼
Durable Run / Task / Tool / Approval events
       │
       ▼
Single RunViewModel
  ├─ execution ribbon
  ├─ nested task tree
  ├─ inline approval card
  └─ developer inspector
```

### Tavily capability

The logical Manifest reference is `mcp: tavily-readonly`. Both local and production composition roots use the same registry factory. The registration points to Tavily's remote MCP endpoint, injects an `Authorization` header at execution time, and exposes only:

- `mcp__tavily__tavily-search`
- `mcp__tavily__tavily-extract`

The key is never placed in the URL, Manifest, event stream, log, or committed configuration. The existing generic secret-reference settings resolve the header value and the runtime redactor removes both the header name and resolved value from SDK-derived payloads.

The agent system prompt must state that web pages are untrusted input, instructions found inside a page are data rather than authority, and claims based on the web should identify their source title and URL.

### Helper subagent

The general agent references a small `helper-agent@1.0.0` with bounded built-in read and analysis tools. The main agent receives the SDK delegation tool and decides when a task benefits from isolated investigation. Tavily remains on the main agent in P0 because the current runtime intentionally rejects custom MCP tools inside subagents.

Subagent activity carries a stable task ID and parent relationship so that the UI can count tasks rather than raw event messages.

### Approval lifecycle

An approval decision is not itself a run terminal event. Approval rejection denies the pending tool invocation and lets the SDK/runtime finish the turn exactly once. The orchestration layer owns the final run terminal transition. This prevents the current sequence where AG-UI emits `RUN_ERROR` before a later `TOOL_CALL_RESULT` arrives.

Approval events and API responses include safe, redacted context:

- tool name and tool call ID;
- command, path, or concise argument summary;
- sandbox/provider identity;
- policy rule and human-readable reason;
- creation and expiry times;
- risk level.

The P0 UI supports approve once and reject. Session-wide allow rules remain P1.

### Single run-state projection

The browser derives one `RunViewModel` from durable activity snapshots/deltas plus tool and approval events. It owns:

- run phase: idle, running, waiting approval, completed, failed, rejected, cancelled;
- active and completed tasks;
- tool calls and their terminal states;
- pending approval;
- elapsed time and counts;
- whether the composer should be enabled.

Components render this projection instead of maintaining competing interpretations of run status. Terminal precedence is explicit and monotonic: once a run is terminal, later duplicate or out-of-order non-terminal events cannot reopen it.

### UI behavior

The default execution display is one compact line:

```text
▸ 正在执行 · 分析代码库 · 3 个工具 · 2 个子任务 · 42s
```

Clicking it expands a nested task/tool tree. The active task is expanded; completed tasks collapse to one row. Approval cards remain expanded and inline because they require action. The developer drawer continues to expose the raw timeline and metrics without making raw events the primary experience.

The page uses a centered conversation column of approximately 920 px, a compact header, a sticky composer, and the optional right inspector. It removes the decorative left `LIVE` rail and excessive empty spacing. Existing graphite, paper, moss, amber, and danger colors remain; no gradients or card-heavy dashboard treatment are added.

## Error handling and safety

- Missing Tavily credentials fail before SDK execution with a named logical credential error.
- MCP connection errors become ordinary tool failures and do not expose authorization material.
- Search/extract are explicitly allowed by policy; all other Tavily tools remain denied by absence.
- Web content is treated as untrusted data in both prompt instructions and source presentation.
- Approval decisions are idempotent; duplicate decisions return the existing outcome.
- Run-state projection tolerates duplicate and out-of-order events.
- A rejected tool does not leave the composer disabled after the run reaches a terminal state.

## Testing strategy

- Unit tests for registry construction, dynamic credentials, exact allowlists, redaction, and policy.
- Runtime fake-transport tests for resolved SDK options and helper-agent definitions.
- Approval service, tool-gate, mapper, and AG-UI integration tests for approve/reject ordering.
- Frontend projection tests for event convergence and monotonic terminal state.
- Component tests for collapsed/expanded tasks and rich approval context.
- Full Python suite, frontend Vitest suite, Next production build, and browser acceptance flows.
- An opt-in Tavily live smoke test uses only local ignored credentials.

## Acceptance criteria

1. The general agent can search and extract a page through Tavily without leaking the key.
2. The general agent can invoke a real helper subagent and the UI groups its work as a task.
3. Approve and reject both finish consistently; no event is sent after an AG-UI terminal event.
4. The composer is re-enabled after every terminal outcome.
5. Execution detail is one line by default and expands on demand.
6. Active, completed, and approval tasks remain understandable without opening the raw event drawer.
7. The full page has no left `LIVE` rail and remains usable at desktop and narrow widths.
8. Existing file, artifact, markdown, tool, and Assistant UI behavior remains covered by tests.
