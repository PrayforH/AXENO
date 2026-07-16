# Markdown Typography Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give assistant Markdown and custom execution surfaces one coherent, Codex-like reading rhythm.

**Architecture:** Keep CopilotKit's Streamdown renderer and add a narrowly scoped CSS typography layer under the chat surface. Protect the contract with a Vitest source-level test, then verify the actual computed styles in the running browser.

**Tech Stack:** Next.js 16, React 19, CopilotKit v2, Streamdown, CSS, Vitest

---

### Task 1: Add the Markdown typography contract

**Files:**
- Create: `web/harness-console/tests/markdown-typography.spec.ts`
- Modify: `web/harness-console/src/app/styles.css`

**Step 1: Write the failing test**

Read `src/app/styles.css` and assert that it contains a scoped Streamdown root,
15px/1.65 body typography, compact heading rules, outside list markers, normalized
quote paragraphs, and a 13px/1.6 fenced-code body.

**Step 2: Run the test to verify it fails**

Run: `npm test -- tests/markdown-typography.spec.ts`

Expected: FAIL because the scoped typography rules do not exist yet.

**Step 3: Add the minimal CSS implementation**

Append a `/* Assistant Markdown typography */` section immediately after the
CopilotKit theme variables. Scope all rules below `.chat-surface [data-copilotkit]`
and select Streamdown semantic elements or `data-streamdown` attributes. Reset
vertical margins explicitly so library spacing utilities cannot stack.

**Step 4: Run the focused test**

Run: `npm test -- tests/markdown-typography.spec.ts`

Expected: PASS.

### Task 2: Verify integration and visual behavior

**Files:**
- Verify: `web/harness-console/src/app/styles.css`
- Verify: `web/harness-console/tests/markdown-typography.spec.ts`

**Step 1: Run the web test suite**

Run: `npm test`

Expected: all tests pass.

**Step 2: Run the production build**

Run: `npm run build`

Expected: Next.js production build exits successfully.

**Step 3: Validate computed styles in the browser**

Send a Markdown fixture through the live harness and inspect the final response.
Confirm body `15px/24.75px`, H2 `19px/26.6px`, quote paragraphs with zero margins,
outside list markers, and fenced code `13px/20.8px`.

**Step 4: Check the patch**

Run: `git diff --check`

Expected: no whitespace errors.

