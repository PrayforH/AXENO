# Code Copy Controls Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Markdown code copying clear and accessible while keeping downloads in artifact cards.

**Architecture:** Add a small client component that enhances Streamdown-owned controls without forking the renderer. Scope visual rules to Streamdown data attributes and CopilotKit message toolbars.

**Tech Stack:** React 19, CopilotKit v2, Streamdown, CSS, Vitest

---

### Task 1: Add the control enhancer

**Files:**
- Create: `web/harness-console/src/components/markdown-control-observer.tsx`
- Create: `web/harness-console/tests/markdown-controls.spec.tsx`
- Modify: `web/harness-console/src/app/page.tsx`

1. Write a failing test for Chinese labels, streamed controls, copied state, and cleanup.
2. Run `npm test -- tests/markdown-controls.spec.tsx` and confirm RED.
3. Implement the minimal observer and mount it beside `ActivityObserver`.
4. Re-run the focused test and confirm GREEN.

### Task 2: Align the visual controls

**Files:**
- Modify: `web/harness-console/src/app/styles.css`
- Modify: `web/harness-console/tests/markdown-typography.spec.ts`

1. Add failing CSS-contract assertions for hidden download, a 32px copy target, and a right-aligned message toolbar.
2. Run the focused tests and confirm RED.
3. Add the scoped CSS rules.
4. Re-run focused tests and confirm GREEN.

### Task 3: Verify and commit

1. Run `npm test`.
2. Run `npm run build`.
3. Inspect live DOM, computed styles, and click feedback in the browser.
4. Run `git diff --check`, commit locally, and preserve `feature/phase-1` without pushing.

