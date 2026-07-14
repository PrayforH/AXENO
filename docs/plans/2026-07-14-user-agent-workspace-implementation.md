# User-Facing Agent Workspace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the internal validation console into a polished end-user Agent task workspace and group multi-turn Run traces into Langfuse Sessions.

**Architecture:** Keep assistant-ui and AG-UI as the interaction foundation. Add a custom assistant-ui welcome component and user-facing run panel, restyle the existing Thread/Composer/activity primitives, and keep raw protocol data behind an advanced disclosure. Extend the OpenTelemetry wrapper with bound attributes so `langfuse.session.id` is applied consistently across API and Worker observations without coupling runtime stages to Langfuse calls.

**Tech Stack:** Python 3.12, OpenTelemetry, pytest, FastAPI, React 19, Next.js 16, assistant-ui, Vitest, CSS.

---

### Task 1: Propagate Harness Session identity to Langfuse

**Files:**
- Modify: `src/harness/observability/provider.py`
- Modify: `src/harness/application/runs.py`
- Modify: `src/harness/worker/orchestrator.py`
- Test: `tests/integration/test_trace_propagation.py`
- Test: `tests/unit/worker/test_orchestrator.py`

**Step 1: Write the failing integration test**

Add a test that binds `{"langfuse.session.id": "session-a"}`, creates a root and child Span, and asserts both exported spans contain the Session attribute. Add a second test that creates two independent root spans with the same bound Session value and asserts their Trace IDs differ while the Session attributes match.

**Step 2: Run the tests and verify RED**

Run:

```bash
uv run pytest tests/integration/test_trace_propagation.py -v
```

Expected: failure because `Observability.bind_attributes` does not exist.

**Step 3: Implement bound and current Span attributes**

In `provider.py`, add a `ContextVar` holding inherited safe attributes and implement:

```python
@contextmanager
def bind_attributes(self, attributes: Mapping[str, AttributeValue]) -> Generator[None]:
    safe = _safe_attributes(attributes)
    token = self._bound_attributes.set({**self._bound_attributes.get(), **safe})
    try:
        yield
    finally:
        self._bound_attributes.reset(token)

def annotate_current_span(self, attributes: Mapping[str, AttributeValue]) -> None:
    span = get_current_span()
    for key, value in _safe_attributes(attributes).items():
        span.set_attribute(key, value)
```

Merge bound attributes before local Span attributes in `span()` so explicit stage attributes win. Preserve redaction.

**Step 4: Bind the Session in API and Worker flows**

- In `RunService.create`, call `annotate_current_span` with `langfuse.session.id`, `session.id`, and the generated `run.id` after the Run ID is known and before injecting Trace Context.
- In `RunOrchestrator.execute`, wrap the worker root and `_execute` call with `bind_attributes({"langfuse.session.id": run.session_id, "session.id": run.session_id})`.
- Keep the existing `run.id` and tenant hash attributes.

**Step 5: Extend the orchestrator trace test**

Assert every exported `harness.*` Span from the arranged Run contains `langfuse.session.id == "session-1"`.

**Step 6: Verify GREEN**

Run:

```bash
uv run pytest tests/integration/test_trace_propagation.py tests/unit/worker/test_orchestrator.py -v
uv run ruff check src/harness/observability/provider.py src/harness/application/runs.py src/harness/worker/orchestrator.py tests/integration/test_trace_propagation.py tests/unit/worker/test_orchestrator.py
uv run pyright src/harness/observability/provider.py src/harness/application/runs.py src/harness/worker/orchestrator.py
```

Expected: all commands pass.

**Step 7: Commit**

```bash
git add src/harness/observability/provider.py src/harness/application/runs.py src/harness/worker/orchestrator.py tests/integration/test_trace_propagation.py tests/unit/worker/test_orchestrator.py
git commit -m "feat: group run traces into langfuse sessions"
```

### Task 2: Replace validation language with user task language

**Files:**
- Modify: `web/harness-console/src/app/page.tsx`
- Modify: `web/harness-console/src/components/developer-drawer.tsx`
- Test: `web/harness-console/tests/workbench-layout.spec.ts`
- Test: `web/harness-console/tests/developer-drawer.spec.ts`

**Step 1: Write failing tests**

Assert the rendered/source UI contains “智能任务助手”, “新任务”, “本次运行”, and “高级诊断”. Assert it no longer contains “交互验证台”, “切换开发者信息”, “Run inspector”, or “协议与原始事件”.

**Step 2: Run tests and verify RED**

```bash
cd web/harness-console && npm test -- workbench-layout.spec.ts developer-drawer.spec.ts
```

Expected: assertions fail against the current internal labels.

**Step 3: Implement the user-facing shell**

- Change the brand eyebrow to `Agent Workspace` and title to “智能任务助手”.
- Rename local state from `developerMode` to `runDetailsOpen`.
- Change actions to “新任务” and “本次运行”/“关闭详情”.
- Keep the existing Thread reset behavior.
- Change the details header eyebrow to `Current run`, empty state to “还没有运行记录”, and raw disclosure to “高级诊断”.
- Keep model, Provider, cost and event data inside the details panel.

**Step 4: Run tests and verify GREEN**

```bash
cd web/harness-console && npm test -- workbench-layout.spec.ts developer-drawer.spec.ts
```

Expected: targeted tests pass.

**Step 5: Commit**

```bash
git add web/harness-console/src/app/page.tsx web/harness-console/src/components/developer-drawer.tsx web/harness-console/tests/workbench-layout.spec.ts web/harness-console/tests/developer-drawer.spec.ts
git commit -m "feat: present harness as a user task workspace"
```

### Task 3: Build the task-first assistant-ui welcome experience

**Files:**
- Modify: `web/harness-console/src/components/agent-thread.tsx`
- Modify: `web/harness-console/src/app/styles.css`
- Test: `web/harness-console/tests/agent-thread-config.spec.tsx`
- Test: `web/harness-console/tests/workbench-layout.spec.ts`

**Step 1: Write the failing component test**

Render the new `UserTaskWelcome` inside a minimal assistant-ui test provider or inspect the component source contract. Assert it includes:

- “今天想让 Agent 完成什么？”
- “分析与规划”
- “阅读与整理”
- “执行与协作”
- “关键操作会先请求确认”

Also assert `Thread` receives `components.ThreadWelcome`.

**Step 2: Run the test and verify RED**

```bash
cd web/harness-console && npm test -- agent-thread-config.spec.tsx workbench-layout.spec.ts
```

Expected: failure because the custom welcome component is absent.

**Step 3: Implement `UserTaskWelcome`**

Compose `ThreadWelcome.Root`, `.Center`, `.Avatar`, and `.Suggestions`. Add a label, heading, explanatory paragraph, and privacy/approval trust line. Pass richer React nodes as the three suggestion `text` values while preserving their prompts and auto-send behavior.

Update Composer placeholder to:

```text
描述你希望完成的任务，可附加文件或资料…
```

Change the footer note to a user trust statement instead of a technology stack label.

**Step 4: Restyle the welcome and Composer**

- Use a subtle warm workspace background and centered content panel.
- Limit the welcome width to the same 57.5rem Thread width.
- Render three differentiated task cards at desktop width and one column below 680px.
- Keep the Composer visually attached to the Thread footer.
- Ensure touch targets are at least 40px and `prefers-reduced-motion` remains effective.

**Step 5: Verify GREEN**

```bash
cd web/harness-console && npm test -- agent-thread-config.spec.tsx workbench-layout.spec.ts
```

Expected: tests pass.

**Step 6: Commit**

```bash
git add web/harness-console/src/components/agent-thread.tsx web/harness-console/src/app/styles.css web/harness-console/tests/agent-thread-config.spec.tsx web/harness-console/tests/workbench-layout.spec.ts
git commit -m "feat: add task-first agent welcome experience"
```

### Task 4: Refine execution and run details for end users

**Files:**
- Modify: `web/harness-console/src/components/activity-summary.tsx`
- Modify: `web/harness-console/src/components/developer-drawer.tsx`
- Modify: `web/harness-console/src/app/styles.css`
- Test: `web/harness-console/tests/execution-ribbon.spec.tsx`
- Test: `web/harness-console/tests/activity-ui.spec.tsx`
- Test: `web/harness-console/tests/developer-drawer.spec.ts`

**Step 1: Add failing user-state assertions**

Assert the collapsed ribbon remains one line, approval and failure phases keep explicit labels, successful runs become visually secondary, and the details panel exposes raw IDs only below “高级诊断”. Add CSS assertions for the mobile bottom panel and desktop right panel.

**Step 2: Run targeted tests and verify RED**

```bash
cd web/harness-console && npm test -- execution-ribbon.spec.tsx activity-ui.spec.tsx developer-drawer.spec.ts
```

**Step 3: Implement the refinements**

- Keep the native `<details>` ribbon collapsed by default.
- Make the summary visually attach to the Composer area.
- Use user-readable section titles “子任务”, “使用的工具”, and “运行模型”.
- Compact the run panel empty state.
- Use a 360px desktop panel and a bottom-sheet layout below 980px with `max-height: 72dvh`.
- Retain approval actions in the main conversation.

**Step 4: Remove conflicting obsolete layout rules**

Delete selectors that target the removed custom `.aui-welcome`, `.aui-message-list`, `.aui-message`, `.aui-viewport-footer`, and `.aui-composer` structures when an active assistant-ui React UI selector supersedes them. Keep `.aui-md`, domain cards, execution components and current `.aui-*-root` overrides.

**Step 5: Verify GREEN**

```bash
cd web/harness-console && npm test -- execution-ribbon.spec.tsx activity-ui.spec.tsx developer-drawer.spec.ts workbench-layout.spec.ts
```

Expected: tests pass.

**Step 6: Commit**

```bash
git add web/harness-console/src/components/activity-summary.tsx web/harness-console/src/components/developer-drawer.tsx web/harness-console/src/app/styles.css web/harness-console/tests
git commit -m "feat: refine user-facing run progress and details"
```

### Task 5: Full verification and browser acceptance

**Files:**
- Modify if required by evidence: `web/harness-console/src/app/styles.css`
- Modify if required by evidence: relevant tests

**Step 1: Run the complete backend verification**

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

Expected: all pass with zero failures.

**Step 2: Run the complete frontend verification**

```bash
cd web/harness-console
npm test
npm run build
```

Expected: all tests and production build pass.

**Step 3: Inspect the desktop page**

Open `http://127.0.0.1:3000/` and verify:

- page title and controls use user task language;
- welcome content forms a clear hierarchy without excessive empty space;
- all three suggestions and Composer are visible;
- opening “本次运行” produces the right-side panel;
- no raw protocol data is visible by default.

**Step 4: Inspect a 390 × 844 viewport**

Verify task cards stack, header controls remain usable, Composer fits without horizontal overflow, and “本次运行” becomes a bottom panel no taller than 72dvh.

**Step 5: Check runtime states**

Use existing deterministic fixtures/tests to verify running, waiting approval, completed, failed, tool, child Agent, Markdown, code and JSON states without invoking a paid external model.

**Step 6: Review and commit any evidence-driven fixes**

```bash
git add <only-files-adjusted-during-acceptance>
git commit -m "fix: polish agent workspace acceptance states"
```

Skip the commit when no files changed.

### Task 6: Completion audit

**Files:**
- Inspect: `docs/plans/2026-07-14-user-agent-workspace-design.md`
- Inspect: current Git diff and log

**Step 1: Audit every design requirement**

For each goal, user experience rule, Langfuse mapping, error state, responsive rule and non-goal, identify source, test, build or browser evidence. Treat missing evidence as incomplete work.

**Step 2: Confirm repository state**

```bash
git status --short
git log --oneline -8
```

Expected: clean worktree and intentional commits only.

**Step 3: Report the outcome**

Summarize the user-visible change, Langfuse behavior, verification commands and any intentionally deferred non-goals.
