# General Agent and Codex Workbench Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add safe Tavily web access and a real helper subagent to the general agent, fix approval/run lifecycle consistency, and replace the always-open activity panel with a Codex-style expandable execution ribbon.

**Architecture:** A shared server-owned MCP registry resolves logical Manifest references and request-scoped secrets for both local and production runtimes. Durable events feed one frontend run projection, which renders a compact execution summary, nested tasks, and inline approvals while the orchestration layer remains the sole owner of terminal run transitions.

**Tech Stack:** Python 3.12, FastAPI, Claude Agent SDK, AG-UI, Pydantic, pytest, Next.js 16, React 19, Assistant UI, TypeScript, Vitest, CSS.

---

### Task 1: Register the Tavily read-only MCP capability

**Files:**
- Create: `src/harness/runtime/default_tools.py`
- Modify: `src/harness/api/dependencies.py`
- Modify: `src/harness/composition.py`
- Test: `tests/unit/runtime/test_default_tools.py`
- Test: `tests/unit/api/test_runtime_composition.py`
- Test: `tests/unit/test_production_composition.py`

**Step 1: Write the failing registry tests**

Add tests that construct the default resolver with a fake credential provider and assert that logical reference `tavily-readonly` resolves to server `tavily`, remote URL `https://mcp.tavily.com/mcp/`, an injected `Authorization` header, and exactly these allowed tools:

```python
assert resolved.allowed_tools == (
    "mcp__tavily__tavily-search",
    "mcp__tavily__tavily-extract",
)
assert resolved.mcp_servers["tavily"]["headers"] == {
    "Authorization": "Bearer test-key"
}
```

Also assert that the resolved value is in `sensitive_values` and that missing credentials raise `McpCredentialError` before runtime execution.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/runtime/test_default_tools.py tests/unit/api/test_runtime_composition.py tests/unit/test_production_composition.py -q`

Expected: FAIL because `default_tools` and shared resolver wiring do not exist.

**Step 3: Implement the shared resolver factory**

Create constants and a small factory:

```python
TAVILY_REFERENCE = "tavily-readonly"
TAVILY_ALLOWED_TOOLS = (
    "mcp__tavily__tavily-search",
    "mcp__tavily__tavily-extract",
)

def default_tool_resolver(
    credential_provider: DynamicMcpCredentialProvider | None = None,
) -> ToolResolver:
    return ToolResolver(
        mcp_registry={
            TAVILY_REFERENCE: McpServerRegistration(
                server_name="tavily",
                config={"type": "http", "url": "https://mcp.tavily.com/mcp/"},
                allowed_tools=TAVILY_ALLOWED_TOOLS,
                credential_headers=(("Authorization", "authorization"),),
            )
        },
        credential_provider=credential_provider,
    )
```

Pass this resolver to `RegistryClaudeRuntime` in both memory/local and production composition roots. Reuse the existing generic secret-reference provider rather than adding a Tavily-specific settings field.

**Step 4: Run focused tests**

Run: `uv run pytest tests/unit/runtime/test_default_tools.py tests/unit/api/test_runtime_composition.py tests/unit/test_production_composition.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/harness/runtime/default_tools.py src/harness/api/dependencies.py src/harness/composition.py tests/unit/runtime/test_default_tools.py tests/unit/api/test_runtime_composition.py tests/unit/test_production_composition.py
git commit -m "feat: register read-only Tavily MCP tools"
```

### Task 2: Allow Tavily safely and opt the general agent into web access

**Files:**
- Modify: `src/harness/policy/rules.py`
- Modify: `tests/unit/policy/test_rules.py`
- Modify: `agents/echo-agent/agent.yaml`
- Modify: `agents/echo-agent/prompts/system.md`
- Modify: `tests/fixtures/agents/echo-agent/agent.yaml`
- Modify: `tests/fixtures/agents/echo-agent/prompts/system.md`
- Modify: `docs/local-development.md`

**Step 1: Write failing policy and manifest tests**

Add policy cases proving search and extract are allowed, while an unrelated Tavily tool remains denied:

```python
assert decide("mcp__tavily__tavily-search").effect is PolicyEffect.ALLOW
assert decide("mcp__tavily__tavily-extract").effect is PolicyEffect.ALLOW
assert decide("mcp__tavily__tavily-crawl").effect is PolicyEffect.DENY
```

Add/extend manifest fixture assertions so the general agent includes `mcp: tavily-readonly` and its version changes from `0.2.0` to `0.3.0`.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/policy/test_rules.py tests/unit/core/test_manifest.py -q`

Expected: FAIL because Tavily tools are not allowed and the Manifest does not reference them.

**Step 3: Add exact policy rules and prompt safeguards**

Add exact ALLOW rules before implicit deny. Update the Manifest to include the logical MCP reference. Update the system prompt to require source title/URL and explicitly treat page instructions as untrusted data.

Document generic local configuration without a real key:

```dotenv
HARNESS_MCP_SECRET_REFERENCES_JSON={"tavily-readonly":{"authorization":"TAVILY_AUTHORIZATION"}}
HARNESS_MCP_SERVER_SECRETS_JSON={"TAVILY_AUTHORIZATION":"Bearer tvly-..."}
```

Store the user-supplied value only in the ignored root `.env` and compose `.env.docker` where applicable.

**Step 4: Run focused tests**

Run: `uv run pytest tests/unit/policy/test_rules.py tests/unit/core/test_manifest.py tests/unit/runtime/test_mcp_credentials.py -q`

Expected: PASS, with no credential value in test output or tracked files.

**Step 5: Commit**

```bash
git add src/harness/policy/rules.py tests/unit/policy/test_rules.py agents/echo-agent tests/fixtures/agents/echo-agent docs/local-development.md
git commit -m "feat: enable safe web research for the general agent"
```

### Task 3: Add and bootstrap a real helper subagent

**Files:**
- Create: `agents/helper-agent/agent.yaml`
- Create: `agents/helper-agent/prompts/system.md`
- Modify: `agents/echo-agent/agent.yaml`
- Modify: `src/harness/cli.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/integration/runtime/test_claude_runtime_fake_transport.py`
- Modify: `tests/unit/runtime/test_registry_runtime.py`

**Step 1: Write failing bootstrap and runtime tests**

Assert bootstrap publishes helper version before echo, echo references `helper-agent@1.0.0`, and resolved SDK options contain the helper Agent definition plus the SDK delegation tool:

```python
assert options.agents["helper-agent"].description
assert "Agent" in options.allowed_tools or "Task" in options.allowed_tools
```

Use the actual tool name exposed by the installed Claude Agent SDK and lock the test to that verified behavior.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_cli.py tests/unit/runtime/test_registry_runtime.py tests/integration/runtime/test_claude_runtime_fake_transport.py -q`

Expected: FAIL because no production helper Manifest is bootstrapped or referenced.

**Step 3: Implement the helper Manifest and bootstrap ordering**

Create a bounded helper that can inspect and reason over files but cannot write, execute shell commands, or access Tavily. Add it as a subagent reference to echo and expose the verified delegation builtin. Ensure the CLI/bootstrap code publishes dependencies before the parent agent.

**Step 4: Run focused tests**

Run: `uv run pytest tests/unit/test_cli.py tests/unit/runtime/test_registry_runtime.py tests/integration/runtime/test_claude_runtime_fake_transport.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add agents/helper-agent agents/echo-agent/agent.yaml src/harness/cli.py tests/unit/test_cli.py tests/unit/runtime/test_registry_runtime.py tests/integration/runtime/test_claude_runtime_fake_transport.py
git commit -m "feat: add helper subagent delegation"
```

### Task 4: Make approval rejection a non-terminal tool decision

**Files:**
- Modify: `src/harness/application/approvals.py`
- Modify: `src/harness/runtime/sdk_tool_gate.py`
- Modify: `src/harness/agui/mapper.py`
- Modify: `tests/unit/application/test_approval_service.py`
- Modify: `tests/unit/runtime/test_sdk_tool_gate.py`
- Modify: `tests/unit/agui/test_mapper.py`
- Modify: `tests/integration/test_approval_flow.py`
- Modify: `tests/integration/agui/test_agui_stream.py`

**Step 1: Reproduce the event-ordering defect with a failing test**

Create a rejection test that records the complete durable and AG-UI sequence. It must assert:

```python
assert event_types.count("run.rejected") == 0
assert agui_types[-1] in {"RUN_FINISHED", "RUN_ERROR"}
assert not any(
    event.type == "TOOL_CALL_RESULT" for event in agui_events[terminal_index + 1 :]
)
```

The exact terminal event follows the runtime's final outcome, but it must occur once and last.

**Step 2: Run the rejection tests to verify they fail**

Run: `uv run pytest tests/unit/application/test_approval_service.py tests/unit/runtime/test_sdk_tool_gate.py tests/integration/test_approval_flow.py tests/integration/agui/test_agui_stream.py -q`

Expected: FAIL because the approval service currently emits a synthetic tool result and transitions the run before the SDK hook finishes.

**Step 3: Implement the smallest lifecycle correction**

Make `ApprovalService.reject` persist and emit `approval.rejected`, resolve the waiting decision, and nothing more. Remove its synthetic `tool.result` and run transition. Let `SdkToolGate` return a deny hook response; let the SDK/runtime emit the actual tool result; let `RunOrchestrator` own the one final run transition.

Keep approval decision handling idempotent by returning the stored terminal decision when the same action is submitted twice.

**Step 4: Run focused approval tests**

Run: `uv run pytest tests/unit/application/test_approval_service.py tests/unit/runtime/test_sdk_tool_gate.py tests/unit/agui/test_mapper.py tests/integration/test_approval_flow.py tests/integration/agui/test_agui_stream.py -q`

Expected: PASS and terminal AG-UI event is last.

**Step 5: Commit**

```bash
git add src/harness/application/approvals.py src/harness/runtime/sdk_tool_gate.py src/harness/agui/mapper.py tests/unit/application/test_approval_service.py tests/unit/runtime/test_sdk_tool_gate.py tests/unit/agui/test_mapper.py tests/integration/test_approval_flow.py tests/integration/agui/test_agui_stream.py
git commit -m "fix: keep approval rejection lifecycle consistent"
```

### Task 5: Enrich approval context without leaking secrets

**Files:**
- Modify: `src/harness/core/models.py`
- Modify: `src/harness/application/types.py`
- Modify: `src/harness/application/approvals.py`
- Modify: `src/harness/runtime/sdk_tool_gate.py`
- Modify: `src/harness/api/schemas.py`
- Modify: `src/harness/api/routes/approvals.py`
- Modify: `src/harness/storage/models.py`
- Add migration if persistence schema requires it: `alembic/versions/*_approval_context.py`
- Modify: `tests/unit/application/test_approval_service.py`
- Modify: `tests/integration/test_approval_flow.py`
- Modify: `web/harness-console/src/components/approval-card.tsx`
- Modify: `web/harness-console/tests/approval.spec.ts`

**Step 1: Write failing API and UI tests**

Test that an approval carries redacted tool name, safe argument summary, sandbox, policy rule, risk, and expiry. Frontend tests should render command/path context and never render authorization fields.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/application/test_approval_service.py tests/integration/test_approval_flow.py -q && cd web/harness-console && npm test -- approval.spec.ts`

Expected: FAIL because the approval model currently contains only reason and IDs.

**Step 3: Add typed safe context**

Add optional fields with backward-compatible defaults. Build the summary in the tool gate after credential redaction. Use a small risk mapping (`low`, `medium`, `high`) based on tool and matched policy rule. Render approve once/reject only; session-wide allow remains out of scope.

**Step 4: Run focused tests**

Run: `uv run pytest tests/unit/application/test_approval_service.py tests/integration/test_approval_flow.py -q && cd web/harness-console && npm test -- approval.spec.ts`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/harness/core/models.py src/harness/application/types.py src/harness/application/approvals.py src/harness/runtime/sdk_tool_gate.py src/harness/api src/harness/storage alembic/versions tests/unit/application/test_approval_service.py tests/integration/test_approval_flow.py web/harness-console/src/components/approval-card.tsx web/harness-console/tests/approval.spec.ts
git commit -m "feat: show safe approval request context"
```

### Task 6: Derive one monotonic frontend RunViewModel

**Files:**
- Create: `web/harness-console/src/lib/run-view-model.ts`
- Create: `web/harness-console/tests/run-view-model.spec.ts`
- Modify: `web/harness-console/src/lib/activity-store.ts`
- Modify: `web/harness-console/tests/activity-store.spec.ts`
- Modify: `web/harness-console/src/components/assistant-runtime-shell.tsx`
- Modify: `web/harness-console/src/components/agent-thread.tsx`

**Step 1: Write failing reducer tests**

Cover running, waiting approval, approved, rejected tool, completed, failed, duplicated, and out-of-order events. Assert terminal states are monotonic and composer enablement is derived from the same phase:

```typescript
expect(reduceRun(terminal, staleRunning).phase).toBe("completed");
expect(selectComposerDisabled(completed)).toBe(false);
```

**Step 2: Run tests to verify they fail**

Run: `cd web/harness-console && npm test -- run-view-model.spec.ts activity-store.spec.ts`

Expected: FAIL because no unified projection exists.

**Step 3: Implement the projection and selectors**

Define typed phases, task/tool nodes, approval state, counts, elapsed time, and terminal precedence. Adapt activity snapshot/delta input into this reducer. Make the shell and thread read phase/composer state from selectors rather than independent booleans.

**Step 4: Run focused tests**

Run: `cd web/harness-console && npm test -- run-view-model.spec.ts activity-store.spec.ts agent-thread-config.spec.tsx`

Expected: PASS, including the existing Assistant UI `ToolFallback` approval regression test.

**Step 5: Commit**

```bash
git add web/harness-console/src/lib/run-view-model.ts web/harness-console/src/lib/activity-store.ts web/harness-console/src/components/assistant-runtime-shell.tsx web/harness-console/src/components/agent-thread.tsx web/harness-console/tests/run-view-model.spec.ts web/harness-console/tests/activity-store.spec.ts web/harness-console/tests/agent-thread-config.spec.tsx
git commit -m "feat: unify frontend run state"
```

### Task 7: Replace the activity panel with an expandable execution ribbon

**Files:**
- Modify: `web/harness-console/src/components/activity-summary.tsx`
- Modify: `web/harness-console/src/components/subagent-card.tsx`
- Modify: `web/harness-console/src/components/tool-card.tsx`
- Modify: `web/harness-console/src/components/agent-thread.tsx`
- Modify: `web/harness-console/tests/activity-ui.spec.tsx`
- Create: `web/harness-console/tests/execution-ribbon.spec.tsx`

**Step 1: Write failing interaction tests**

Assert the default DOM exposes one summary row, details are hidden, click/keyboard activation expands them, tasks group by stable task/parent IDs, completed tasks collapse, active tasks open, and pending approvals stay visible.

**Step 2: Run tests to verify they fail**

Run: `cd web/harness-console && npm test -- execution-ribbon.spec.tsx activity-ui.spec.tsx`

Expected: FAIL because the current summary renders the last four events and has no task grouping.

**Step 3: Implement ribbon and task tree**

Use a native accessible disclosure button. Render a compact line such as:

```text
正在执行 · 分析代码库 · 3 个工具 · 2 个子任务 · 42s
```

On expansion, render the RunViewModel tree. Count distinct task IDs rather than activity messages. Preserve the detailed ToolCard and SubagentCard inside nodes.

**Step 4: Run focused tests**

Run: `cd web/harness-console && npm test -- execution-ribbon.spec.tsx activity-ui.spec.tsx structured-value.spec.tsx`

Expected: PASS.

**Step 5: Commit**

```bash
git add web/harness-console/src/components/activity-summary.tsx web/harness-console/src/components/subagent-card.tsx web/harness-console/src/components/tool-card.tsx web/harness-console/src/components/agent-thread.tsx web/harness-console/tests/activity-ui.spec.tsx web/harness-console/tests/execution-ribbon.spec.tsx
git commit -m "feat: add expandable execution ribbon"
```

### Task 8: Tighten the full-page workbench layout and source presentation

**Files:**
- Modify: `web/harness-console/src/app/page.tsx`
- Modify: `web/harness-console/src/app/styles.css`
- Modify: `web/harness-console/src/components/markdown-text.tsx`
- Create: `web/harness-console/src/components/source-link.tsx`
- Create: `web/harness-console/tests/source-link.spec.tsx`
- Modify: `web/harness-console/tests/markdown-typography.spec.ts`

**Step 1: Write failing semantic/style tests**

Assert the `LIVE` rail is absent, the conversation uses the workbench container, the composer is sticky, and source links show title plus external URL with safe link attributes.

**Step 2: Run tests to verify they fail**

Run: `cd web/harness-console && npm test -- source-link.spec.tsx markdown-typography.spec.ts`

Expected: FAIL because the rail remains and there is no dedicated source treatment.

**Step 3: Implement the approved visual direction**

Remove the left rail and hardcoded echo version label. Center the conversation at roughly 920 px, compact header spacing, keep the developer drawer optional, and preserve the existing palette. Add source-link styling without gradients or nested card chrome. Ensure responsive behavior below 900 px.

**Step 4: Run focused tests and build**

Run: `cd web/harness-console && npm test -- source-link.spec.tsx markdown-typography.spec.ts && npm run build`

Expected: PASS and Next production build completes.

**Step 5: Commit**

```bash
git add web/harness-console/src/app/page.tsx web/harness-console/src/app/styles.css web/harness-console/src/components/markdown-text.tsx web/harness-console/src/components/source-link.tsx web/harness-console/tests/source-link.spec.tsx web/harness-console/tests/markdown-typography.spec.ts
git commit -m "feat: refine the Codex-style agent workbench"
```

### Task 9: Verify Tavily, delegation, approvals, and responsive UI end to end

**Files:**
- Create: `tests/integration/runtime/test_tavily_mcp_live.py`
- Modify: `tests/e2e/test_local_stack.py`
- Modify: `README.md`
- Modify: `docs/domain-agents.md`
- Modify: `docs/local-development.md`

**Step 1: Add opt-in smoke coverage**

Create a live test skipped unless generic MCP secret settings contain the Tavily reference. It should ask a deterministic current-information question, assert at least one allowed Tavily tool call, assert a source URL in the answer, and scan all captured events for the credential value.

**Step 2: Run focused live validation**

Run: `uv run pytest tests/integration/runtime/test_tavily_mcp_live.py -q`

Expected: PASS when the local ignored credential is configured; otherwise SKIP with a clear reason.

**Step 3: Run complete automated verification**

Run:

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
cd web/harness-console
npm test
npm run build
```

Expected: all checks pass with no warnings that indicate leaked secrets or state-update errors.

**Step 4: Perform browser acceptance**

At `http://127.0.0.1:3000`, verify:

1. ordinary greeting produces a concise answer;
2. a current-information question invokes Tavily and cites sources;
3. a decomposition request invokes the helper agent and groups it as a task;
4. a Bash/write request shows rich approval context;
5. approve continues and finishes;
6. reject finishes without `TOOL_CALL_RESULT after RUN_ERROR` and re-enables composer;
7. execution is one line by default and expands;
8. desktop and narrow widths remain readable.

**Step 5: Document capability composition for domain agents**

Explain how a domain agent opts into `mcp: tavily-readonly`, references helper agents, adds policy-tested tools, and relies on the shared approval/run UI rather than forking the harness.

**Step 6: Commit**

```bash
git add tests/integration/runtime/test_tavily_mcp_live.py tests/e2e/test_local_stack.py README.md docs/domain-agents.md docs/local-development.md
git commit -m "docs: verify and document general agent capabilities"
```

### Task 10: Final review and delivery

**Files:**
- Review all changed files from `git diff --stat main...HEAD`

**Step 1: Run secret and stale-label checks**

Run:

```bash
git grep -nE 'tvly-|dtn_|sk-lf-|pk-lf-' -- ':!docs/plans/*'
git grep -n 'LIVE\|echo-agent 0.2.0' -- web/harness-console
```

Expected: no real secrets and no stale decorative labels.

**Step 2: Review scope and commit history**

Run: `git status --short && git log --oneline --decorate -12`

Expected: only intentional changes, with the prior Assistant UI `ToolFallback` approval fix included in the appropriate frontend commit.

**Step 3: Use required verification skill**

Invoke `@superpowers:verification-before-completion`, rerun the commands it requires, and report exact evidence rather than relying on earlier runs.

**Step 4: Report delivery**

Summarize implemented P0 capabilities, verification results, how future domain agents consume the foundation, and any P1/P2 items intentionally deferred. Do not push or update GitHub unless the user explicitly asks.
