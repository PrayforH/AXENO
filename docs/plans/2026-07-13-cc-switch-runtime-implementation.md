# cc-switch Claude Runtime Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make local Harness startup optionally execute Agents through Claude Agent SDK using the active cc-switch Claude configuration without persisting or logging credentials.

**Architecture:** A strict loader reads only the supported Anthropic environment fields from the cc-switch-applied `~/.claude/settings.json`. A registry-backed runtime resolves the published AgentVersion for each Session, then delegates to the existing `ClaudeSdkRuntime`; the application composition root chooses this runtime only when `HARNESS_RUNTIME=claude-sdk`, otherwise preserving Fake Runtime.

**Tech Stack:** Python 3.12, Pydantic Settings, Claude Agent SDK, FastAPI, pytest, Bash/Make, Next.js/CopilotKit.

---

### Task 1: Parse the active cc-switch Claude configuration safely

**Files:**
- Create: `src/harness/runtime/cc_switch.py`
- Create: `tests/unit/runtime/test_cc_switch.py`
- Modify: `src/harness/config.py`

**Step 1: Write failing tests**

Cover a valid `env` object, auth-token versus API-key provider selection, missing/invalid JSON, missing endpoint/model/credential, `~` expansion, and the guarantee that credential text is absent from exceptions and repr.

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/runtime/test_cc_switch.py -q`
Expected: FAIL because `harness.runtime.cc_switch` does not exist.

**Step 3: Implement the minimal loader**

Add an immutable `CcSwitchClaudeConfig` containing `base_url`, `model`, `provider`, and `SecretStr credential`. Read the configured path, require a JSON object with an `env` object, and use this precedence:

```python
model = env.get("ANTHROPIC_MODEL") or env.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
credential = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")
provider = "new-api" if env.get("ANTHROPIC_AUTH_TOKEN") else "anthropic"
```

Add `cc_switch_settings_path` to `Settings`, defaulting to `~/.claude/settings.json`.

**Step 4: Verify GREEN**

Run: `uv run pytest tests/unit/runtime/test_cc_switch.py tests/unit/test_config.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/harness/config.py src/harness/runtime/cc_switch.py tests/unit/runtime/test_cc_switch.py tests/unit/test_config.py
git commit -m "feat: load active cc-switch claude config"
```

### Task 2: Resolve Claude SDK runtime from the published AgentVersion

**Files:**
- Create: `src/harness/runtime/registry_runtime.py`
- Create: `tests/unit/runtime/test_registry_runtime.py`

**Step 1: Write a failing async test**

Publish a fixture AgentVersion into `InMemoryAgentRegistry`, create a Session context, inject a fake SDK query factory, and assert the wrapper resolves the exact tenant/name/version before emitting the existing mapped SDK events.

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/runtime/test_registry_runtime.py -q`
Expected: FAIL because `RegistryClaudeRuntime` does not exist.

**Step 3: Implement the delegating runtime**

`RegistryClaudeRuntime.execute()` calls `AgentRegistry.get()` using the Session fields, builds one `ModelRoute` named `new-api-default` from the immutable cc-switch config, constructs `ClaudeSdkRuntime`, and yields its events. Keep the credential inside `SecretStr` until populating `route_secrets`.

**Step 4: Verify GREEN**

Run: `uv run pytest tests/unit/runtime/test_registry_runtime.py tests/integration/runtime/test_claude_runtime_fake_transport.py -q`
Expected: PASS and no credential in event repr.

**Step 5: Commit**

```bash
git add src/harness/runtime/registry_runtime.py tests/unit/runtime/test_registry_runtime.py
git commit -m "feat: resolve sdk runtime from agent registry"
```

### Task 3: Select the configured runtime in the application composition root

**Files:**
- Modify: `src/harness/api/dependencies.py`
- Modify: `src/harness/api/app.py`
- Create: `tests/unit/api/test_runtime_composition.py`

**Step 1: Write failing composition tests**

Assert default settings install `FakeRuntime`; `runtime="claude-sdk"` with a temporary cc-switch file installs `RegistryClaudeRuntime`; missing settings fail during startup; and no fallback occurs.

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/api/test_runtime_composition.py -q`
Expected: FAIL because the composition root always installs Fake Runtime.

**Step 3: Implement minimal selection**

Allow `build_memory_container()` and `create_memory_app()` to accept one `Settings` instance. Reuse it for observability and runtime construction. At module startup, construct Settings once and pass it through.

**Step 4: Verify GREEN**

Run: `uv run pytest tests/unit/api/test_runtime_composition.py tests/e2e/test_local_stack.py -q`
Expected: PASS; default E2E remains Fake Runtime.

**Step 5: Commit**

```bash
git add src/harness/api/dependencies.py src/harness/api/app.py tests/unit/api/test_runtime_composition.py
git commit -m "feat: select claude sdk runtime at startup"
```

### Task 4: Add a reproducible cc-switch local startup mode

**Files:**
- Modify: `Makefile`
- Modify: `scripts/dev_up.sh`
- Modify: `web/harness-console/src/components/chat-console.tsx`
- Modify: `README.md`
- Modify: `docs/local-development.md`
- Test: `web/harness-console/tests/console.spec.ts`

**Step 1: Write failing tests**

Assert the console runtime badge is derived from `NEXT_PUBLIC_HARNESS_RUNTIME` and that the documented command is `make dev-up-cc-switch`.

**Step 2: Verify RED**

Run: `make web-test`
Expected: FAIL because the UI is hard-coded to Fake Runtime and the target is absent.

**Step 3: Implement startup wiring**

Add `dev-up-cc-switch` that invokes `dev_up.sh` with `HARNESS_RUNTIME=claude-sdk`. Forward that value to the API and as `NEXT_PUBLIC_HARNESS_RUNTIME` to Next.js. Display `Claude SDK · cc-switch` for the real mode and preserve the existing Fake label otherwise. Document restart semantics and credential safety.

**Step 4: Verify GREEN**

Run: `make web-test && COPILOTKIT_TELEMETRY_DISABLED=true make web-build`
Expected: all Web tests pass and production build succeeds.

**Step 5: Commit**

```bash
git add Makefile scripts/dev_up.sh web/harness-console/src/components/chat-console.tsx web/harness-console/tests README.md docs/local-development.md
git commit -m "feat: start local harness from cc-switch"
```

### Task 5: Full verification and live cc-switch acceptance

**Files:**
- No production files expected

**Step 1: Run the full automated gate**

Run: `make verify && make web-test && COPILOTKIT_TELEMETRY_DISABLED=true make web-build`
Expected: zero failures.

**Step 2: Stop Fake Runtime and start the cc-switch mode**

Run: `make dev-down && make dev-up-cc-switch`
Expected: startup identifies `claude-sdk` without printing credentials; PostgreSQL, Redis, MinIO, API, and Web are ready.

**Step 3: Run a direct AG-UI real-model smoke**

POST a normal Chinese prompt through `/api/copilotkit/agent/harness-agent/run`. Assert `RUN_FINISHED`, non-empty assistant content, and content is not prefixed with `Echo:`.

**Step 4: Verify in the WebUI**

Reload `http://127.0.0.1:3000`, assert the badge reads `Claude SDK · cc-switch`, send a normal prompt, observe a real response, and inspect fresh browser logs for errors.

**Step 5: Final safety checks**

Run `git diff --check`, inspect logs for leaked credential values using only a hash/presence comparison, confirm `git status` is clean, and leave the local services running.
