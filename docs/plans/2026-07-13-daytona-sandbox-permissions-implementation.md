# Daytona Sandbox Development Permissions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow explicitly declared file-development tools without approval for every user running in a Daytona container, while retaining approval for local writes and all Bash execution.

**Architecture:** Add a server-owned isolation level to `SandboxHandle`, propagate it through `RuntimeContext` into `PolicyContext`, and let deterministic policy rules match that trusted fact. Agent Manifests remain the tool capability allowlist; the validation Agent explicitly declares the wider tool set so the browser can exercise the policy.

**Tech Stack:** Python 3.12, Pydantic v2, Claude Agent SDK hooks, pytest, YAML Agent Manifests.

---

### Task 1: Model the trusted Sandbox isolation level

**Files:**
- Modify: `src/harness/sandbox/base.py`
- Modify: `src/harness/sandbox/daytona.py`
- Modify: `src/harness/runtime/base.py`
- Test: `tests/unit/sandbox/test_daytona.py`
- Test: `tests/unit/sandbox/test_local.py`
- Test: `tests/unit/core/test_platform_models.py`

**Step 1: Write the failing tests**

Assert that a local handle has `SandboxIsolation.WORKSPACE`, a Daytona handle has `SandboxIsolation.CONTAINER`, and `RuntimeContext` rejects an invalid isolation value.

**Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/unit/sandbox/test_local.py tests/unit/sandbox/test_daytona.py tests/unit/core/test_platform_models.py -q
```

Expected: collection or assertion failure because `SandboxIsolation` and the fields do not exist.

**Step 3: Implement the minimal model**

Add:

```python
class SandboxIsolation(StrEnum):
    WORKSPACE = "workspace"
    CONTAINER = "container"
```

Set `SandboxHandle.isolation_level` to `WORKSPACE` by default, return `CONTAINER` from Daytona, and add immutable `sandbox_provider` and `sandbox_isolation` facts to `RuntimeContext` with conservative local defaults.

**Step 4: Run tests to verify GREEN**

Run the Task 1 command and expect all selected tests to pass.

**Step 5: Commit**

```bash
git add src/harness/sandbox src/harness/runtime/base.py tests/unit/sandbox tests/unit/core/test_platform_models.py
git commit -m "feat: model sandbox isolation level"
```

### Task 2: Make policy decisions isolation-aware

**Files:**
- Modify: `src/harness/policy/models.py`
- Modify: `src/harness/policy/rules.py`
- Test: `tests/unit/policy/test_rules.py`

**Step 1: Write the failing policy matrix**

Parameterize both isolation levels and assert:

- `Read`, `Glob`, and `Grep` are allowed in both environments.
- `Write` and `Edit` ask in a local workspace and are allowed in a container.
- `Bash` asks in both environments.
- local `rm ` is denied while container `rm ` still asks.
- an unknown tool is denied.

Add a test proving a more specific isolation rule wins over a generic tool rule.

**Step 2: Run tests to verify RED**

```bash
uv run pytest tests/unit/policy/test_rules.py -q
```

Expected: failures for missing isolation matching and missing tool rules.

**Step 3: Implement the minimal policy changes**

Add `sandbox_isolation` to `PolicyContext` and optional `sandbox_isolation` to `PolicyRule`. Include the new field in `_matches` and `_specificity`. Extend default rules with `Glob`, `Grep`, `Edit`, container-specific `Write`/`Edit` allows, and scope destructive local Bash denial to `WORKSPACE`.

**Step 4: Run tests to verify GREEN**

Run the Task 2 command and expect all tests to pass.

**Step 5: Commit**

```bash
git add src/harness/policy tests/unit/policy/test_rules.py
git commit -m "feat: authorize tools by sandbox isolation"
```

### Task 3: Propagate actual Sandbox facts into the SDK Gate

**Files:**
- Modify: `src/harness/worker/orchestrator.py`
- Modify: `src/harness/runtime/sdk_tool_gate.py`
- Test: `tests/unit/worker/test_orchestrator.py`
- Test: `tests/unit/runtime/test_sdk_tool_gate.py`

**Step 1: Write the failing propagation tests**

Add a capturing Runtime test proving the Worker passes the provisioned provider and isolation level into `RuntimeContext`. Add SDK Gate tests proving container `Write` is allowed without `approval.requested`, local `Write` waits for approval, and a fake `sandbox_isolation` tool argument cannot change the decision. Assert the persisted `tool.request` includes only the trusted provider and isolation metadata.

**Step 2: Run tests to verify RED**

```bash
uv run pytest tests/unit/worker/test_orchestrator.py tests/unit/runtime/test_sdk_tool_gate.py -q
```

Expected: assertions fail because the facts are not propagated or evaluated.

**Step 3: Implement the minimal propagation**

Build `RuntimeContext` from `handle.provider` and `handle.isolation_level`. In `SdkToolGate`, add those trusted values to `tool.request` and use `context.sandbox_isolation` when constructing `PolicyContext`; never inspect tool arguments for this decision.

**Step 4: Run tests to verify GREEN**

Run the Task 3 command and expect all tests to pass.

**Step 5: Commit**

```bash
git add src/harness/worker/orchestrator.py src/harness/runtime/sdk_tool_gate.py tests/unit/worker/test_orchestrator.py tests/unit/runtime/test_sdk_tool_gate.py
git commit -m "feat: enforce trusted sandbox permissions"
```

### Task 4: Expose the development tools in the validation Agent

**Files:**
- Modify: `agents/echo-agent/agent.yaml`
- Modify: `agents/echo-agent/prompts/system.md`
- Test: `tests/unit/core/test_manifest.py`

**Step 1: Write the failing Agent package test**

Load `agents/echo-agent/agent.yaml` and assert the declared builtins are exactly `Read`, `Glob`, `Grep`, `Write`, `Edit`, and `Bash`. Assert its prompt tells the Agent to modify files only when the user requests it and to keep outputs within the run workspace.

**Step 2: Run tests to verify RED**

```bash
uv run pytest tests/unit/core/test_manifest.py -q
```

Expected: failure because the validation Agent declares only `Read`.

**Step 3: Update the Agent package**

Declare the six tools explicitly and replace the echo-only prompt with a concise workspace validation mission that does not force a canned self-introduction or echo response.

**Step 4: Run tests to verify GREEN**

Run the Task 4 command and validate the package:

```bash
uv run harness agent validate agents/echo-agent/agent.yaml
```

Expected: tests pass and the CLI prints a valid content hash.

**Step 5: Commit**

```bash
git add agents/echo-agent tests/unit/core/test_manifest.py
git commit -m "feat: equip validation agent for workspace tasks"
```

### Task 5: Document and verify the permission boundary

**Files:**
- Modify: `docs/domain-agents.md`
- Modify: `docs/local-development.md`
- Modify: `README.md`

**Step 1: Update operator documentation**

Document the two-layer Manifest/policy model, the local-vs-Daytona decision table, why Bash remains approval-gated, and how to select Daytona for real workspace validation.

**Step 2: Run focused and full verification**

```bash
git diff --check
uv run pytest tests/unit/sandbox tests/unit/policy tests/unit/runtime/test_sdk_tool_gate.py tests/unit/worker/test_orchestrator.py tests/unit/core/test_manifest.py -q
make verify
```

Expected: formatting clean, focused tests pass, and the complete Python verification suite succeeds.

**Step 3: Verify the Web console regression suite**

```bash
cd web/harness-console
npm test
npm run build
```

Expected: all Web tests pass and Next.js production build completes.

**Step 4: Commit**

```bash
git add README.md docs/domain-agents.md docs/local-development.md
git commit -m "docs: explain sandbox development permissions"
```

### Task 6: Runtime smoke test and PR update

**Files:**
- No production file changes expected.

**Step 1: Restart the local validation services and republish the changed Agent version**

Use the existing local startup workflow, publish the updated `agents/echo-agent/agent.yaml`, and create a fresh AG-UI thread.

**Step 2: Verify local behavior**

Send a workspace-writing request and verify that `Write` produces an approval request. Send `你好` in a fresh thread and verify the response is not the previous canned Claude self-introduction.

**Step 3: Verify Daytona behavior when credentials are configured**

Run the same file-writing request with `HARNESS_SANDBOX_PROVIDER=daytona` and verify `Write` proceeds without `approval.requested`, while `Bash` still creates one. If Daytona credentials are unavailable, retain the automated provider/Gate evidence and report the external smoke-test limitation explicitly.

**Step 4: Push and update the existing Draft PR**

Push `feature/phase-1` and update the Draft PR description with the permission model, Langfuse integration, and fresh verification evidence.
