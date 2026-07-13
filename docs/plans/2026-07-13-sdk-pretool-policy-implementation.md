# Claude SDK PreToolUse Policy Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development task-by-task.

**Goal:** Guarantee Harness policy and human approval run before every real Claude SDK tool execution without starting a duplicate Worker.

**Architecture:** `SdkToolGate` creates a catch-all PreToolUse hook per RuntimeContext. It writes policy events and delegates ASK decisions to an inline Future managed by `ApprovalService`. The approval route distinguishes inline waiters from resumable Fake Runtime pauses. ClaudeSdkRuntime installs the hook and suppresses the later duplicate tool request projection.

**Tech Stack:** Python 3.12 asyncio, Claude Agent SDK hooks, FastAPI, pytest.

---

### Task 1: Add inline approval waiting semantics

Write failing tests for waiter registration-before-event, approve/reject wakeup, cleanup, and the route's no-second-worker decision. Implement minimal Future management in `ApprovalService` while preserving existing non-inline behavior.

### Task 2: Add SdkToolGate

Write failing tests for ALLOW, DENY, ASK-approved, ASK-rejected and durable event ordering. Implement one catch-all PreToolUse Hook returning typed SDK hook outputs.

### Task 3: Wire and deduplicate

Write failing Runtime/composition tests proving hooks are installed in real mode, duplicate SDK tool requests are suppressed only when gated, tool results remain, and Fake Runtime remains unchanged. Inject the Gate in `build_memory_container`.

### Task 4: Verify and smoke

Run `make verify`, Web tests/build, a fake approval E2E, and a real cc-switch Read/Bash-deny smoke. Update domain docs with the completed safety boundary and remaining multi-process limitation.

