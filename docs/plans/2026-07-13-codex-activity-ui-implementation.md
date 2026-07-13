# Codex-Style Agent Activity UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Codex-style execution summary, rich tool/subagent rendering, structured JSON/code/diff views, and a replayable Run Inspector while preserving CopilotKit Chat.

**Architecture:** Claude SDK messages are normalized into durable Harness activity and subagent events. The AG-UI mapper maintains one replayable ActivityMessage per Run using `ACTIVITY_SNAPSHOT` followed by JSON-patch `ACTIVITY_DELTA` events, while standard message/tool events remain intact. CopilotKit renders a compact activity message in chat and exposes the same durable activity content in a responsive developer Inspector.

**Tech Stack:** Python 3.12, Claude Agent SDK, FastAPI, AG-UI protocol, pytest, React 19, Next.js 16, CopilotKit v2, TypeScript, Vitest, CSS.

---

### Task 1: Normalize runtime activity and isolate subagent streams

**Files:**
- Modify: `src/harness/runtime/message_mapper.py`
- Modify: `src/harness/runtime/claude_sdk.py`
- Modify: `tests/unit/runtime/test_message_mapper.py`
- Modify: `tests/integration/runtime/test_claude_runtime_fake_transport.py`

**Steps:**

1. Add failing tests for `TaskStartedMessage`, `TaskProgressMessage`, `TaskNotificationMessage`, `TaskUpdatedMessage`, safe `runtime.system` metadata, and a child `StreamEvent` whose text must appear only in `subagent.delta`.
2. Run the focused tests and confirm failures are caused by missing mappings.
3. Map task lifecycle messages to `subagent.started`, `subagent.progress`, and `subagent.completed|failed`; whitelist task ID, description, status, usage, summary, tool-use ID and last tool name.
4. Put child text and parent tool-use ID in `subagent.delta`; do not emit main `message.delta` for child streams.
5. Preserve current main-message lifecycle/deduplication and run Ruff, Pyright and focused tests.
6. Commit `feat: normalize sdk activity and subagent events`.

### Task 2: Resolve manifest subagents for real SDK delegation

**Files:**
- Modify: `src/harness/runtime/registry_runtime.py`
- Modify: `src/harness/runtime/claude_sdk.py`
- Modify: `scripts/bootstrap_local_agent.py`
- Modify: `tests/fixtures/agents/echo-agent/agent.yaml`
- Create: `tests/fixtures/agents/helper-agent/agent.yaml`
- Create: `tests/fixtures/agents/helper-agent/prompts/system.md`
- Modify: `tests/unit/runtime/test_registry_runtime.py`
- Modify: `tests/e2e/test_local_stack.py`

**Steps:**

1. Add failing tests proving `helper-agent@1.0.0` is resolved from the registry and converted to an SDK `AgentDefinition` with its prompt and tools.
2. Add optional `subagent_versions` to `ClaudeSdkRuntime`; construct `ClaudeAgentOptions.agents` from immutable referenced AgentVersion snapshots.
3. Resolve every explicit `name@version` reference in `RegistryClaudeRuntime`; fail clearly when missing.
4. Publish helper before echo-agent in local bootstrap and add `Task` to the parent tool allowlist.
5. Verify bootstrap idempotency, fake transport options and no prompt/token leakage in events.
6. Commit `feat: resolve manifest subagents for sdk runtime`.

### Task 3: Project one replayable AG-UI activity message per Run

**Files:**
- Create: `src/harness/agui/activity.py`
- Modify: `src/harness/agui/mapper.py`
- Create: `tests/unit/agui/test_activity.py`
- Modify: `tests/unit/agui/test_mapper.py`
- Modify: `tests/integration/agui/test_agui_stream.py`

**Steps:**

1. Add failing tests for the initial `ActivitySnapshotEvent`, subsequent `ActivityDeltaEvent` append/status patches, metadata whitelist, suppression of token-level noise, and replay order.
2. Implement pure `activity_projection(event)` returning zero or one activity event. Use `activity-{run_id}` as the stable message ID and `harness.run.v1` as `activityType`.
3. Snapshot `run.queued` with the first timeline item; append salient run, model, message, tool, approval, subagent, artifact and result events via JSON Patch.
4. Add model/provider/turns/cost/stop reason to whitelisted metadata; never include runtime secrets, prompts or raw thinking.
5. Compose the activity event with existing AG-UI standard events and prove connect replay rebuilds one ActivityMessage.
6. Commit `feat: project durable run activity to ag-ui`.

### Task 4: Build safe structured JSON, code and diff primitives

**Files:**
- Create: `web/harness-console/src/components/structured-value.tsx`
- Create: `web/harness-console/src/components/code-block.tsx`
- Create: `web/harness-console/src/components/diff-block.tsx`
- Create: `web/harness-console/src/lib/content-format.ts`
- Create: `web/harness-console/tests/content-format.spec.ts`
- Create: `web/harness-console/tests/structured-value.spec.tsx`

**Steps:**

1. Add failing tests for JSON parsing, unified-diff detection, fenced-code extraction, circular/invalid input fallback, truncation limits and safe HTML treatment.
2. Implement pure format detection and truncation helpers.
3. Implement recursive JSON rows with depth-two defaults, type classes, raw/tree tabs and copy controls.
4. Implement code and diff blocks with labels, line numbers, copy, horizontal scroll, long-content folding and accessible buttons.
5. Render representative fixtures with `react-dom/server`, run Vitest and TypeScript build.
6. Commit `feat: add structured agent output renderers`.

### Task 5: Replace default tool UI and render activity/subagents

**Files:**
- Modify: `web/harness-console/src/components/harness-tool-renderers.tsx`
- Replace: `web/harness-console/src/components/tool-card.tsx`
- Create: `web/harness-console/src/components/activity-summary.tsx`
- Create: `web/harness-console/src/components/subagent-card.tsx`
- Create: `web/harness-console/src/lib/activity-schema.ts`
- Modify: `web/harness-console/src/components/copilotkit-shell.tsx`
- Create: `web/harness-console/tests/activity-schema.spec.ts`
- Create: `web/harness-console/tests/activity-summary.spec.tsx`
- Create: `web/harness-console/tests/tool-card.spec.tsx`

**Steps:**

1. Add failing schema and server-render tests for running/completed summaries, generic tools, `Task`/`Agent` subagents, malformed parameters and result rendering.
2. Register a stable `ReactActivityMessageRenderer` for `harness.run.v1` on the CopilotKit provider.
3. Replace `useDefaultRenderTool()` with a custom wildcard renderer using the rich value primitives.
4. Register `Task` and `Agent` renderers as subagent cards; keep approval and Artifact specialized.
5. Ensure main chat renders one compact activity summary with expandable salient steps, counts and duration.
6. Commit `feat: render codex-style agent activities`.

### Task 6: Build the responsive Run Inspector and visual system

**Files:**
- Replace: `web/harness-console/src/components/developer-drawer.tsx`
- Create: `web/harness-console/src/components/execution-spine.tsx`
- Modify: `web/harness-console/src/app/page.tsx`
- Modify: `web/harness-console/src/app/styles.css`
- Modify: `web/harness-console/tests/developer-drawer.spec.ts`
- Create: `web/harness-console/tests/execution-spine.spec.tsx`

**Steps:**

1. Add failing tests for extracting the current Run activity from `useAgent` messages and rendering metrics/timeline/empty/error states.
2. Replace the bottom strip with a 360px right Inspector on desktop and bottom drawer under 860px.
3. Render chronological activity nodes, status, model/provider, duration, turns, cost and stop reason; keep CopilotKit Inspector behind an “原始事件” disclosure.
4. Apply the approved palette, typography, compact spacing, execution spine, focus states, mobile layout and reduced-motion rules.
5. Take before/after screenshots at desktop and narrow viewport; remove decorative elements that do not encode state.
6. Commit `feat: add responsive run inspector`.

### Task 7: Full regression and real-model browser acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/local-development.md`

**Steps:**

1. Run `make verify && make web-test && COPILOTKIT_TELEMETRY_DISABLED=true make web-build`.
2. Restart `HARNESS_RUNTIME=claude-sdk` with the current cc-switch provider and bootstrap both Agent manifests.
3. Validate in the browser: ordinary response, a Read tool request, a helper subagent delegation, Run Inspector, JSON/code/diff expansion, copy controls, replay after refresh and mobile layout.
4. Confirm child-agent output does not occur in the main assistant message and browser logs contain no application errors.
5. Scan tracked files/events/logs for the active credential and raw thinking; verify clean worktree and healthy services.
6. Update docs with validation prompts and screenshots/behavior descriptions; commit `docs: explain codex-style activity validation`.
