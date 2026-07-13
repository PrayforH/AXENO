# Domain Agent Tool Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve Manifest builtin/Python/MCP tools into Claude Agent SDK options and provide a minimal CLI for creating and validating domain Agent packages.

**Architecture:** A fail-closed `ToolResolver` turns logical Manifest references into immutable builtin, MCP server, and explicit allowlist collections. Python exports are in-process SDK MCP tools; external MCP references are supplied by a server-owned registry. `ClaudeSdkRuntime` consumes the resolved result. A small argparse CLI reuses the production Manifest publisher for scaffolding validation.

**Tech Stack:** Python 3.12, Claude Agent SDK, Pydantic, argparse, pytest, Ruff, Pyright.

---

### Task 1: Add the fail-closed Tool Resolver

**Files:**
- Create: `src/harness/runtime/tools.py`
- Create: `tests/unit/runtime/test_tools.py`

**Step 1: Write failing tests**

Cover builtin preservation, a valid `SdkMcpTool` Python export, multiple Python exports, external MCP lookup, explicit allowed tools, unknown registrations, malformed Python references, invalid exports, duplicate tool names, and sanitized errors.

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/runtime/test_tools.py -q`
Expected: FAIL because `harness.runtime.tools` does not exist.

**Step 3: Implement the minimal resolver**

Add immutable `McpServerRegistration`, `ResolvedTools`, and `ToolResolver`. Import `module:attribute`, require `SdkMcpTool` values, create one `harness-python` server with `create_sdk_mcp_server`, and resolve external MCP logical IDs from an injected mapping.

**Step 4: Verify GREEN**

Run: `uv run pytest tests/unit/runtime/test_tools.py -q`
Expected: PASS.

### Task 2: Wire resolved tools into Claude SDK Runtime

**Files:**
- Modify: `src/harness/runtime/claude_sdk.py`
- Modify: `src/harness/runtime/registry_runtime.py`
- Modify: `src/harness/api/dependencies.py`
- Modify: `tests/integration/runtime/test_claude_runtime_fake_transport.py`
- Modify: `tests/unit/runtime/test_registry_runtime.py`

**Step 1: Write failing integration tests**

Assert Python/MCP servers and explicit allowed tools reach `ClaudeAgentOptions`; builtins remain unchanged; subagent custom tools fail instead of being ignored; Registry Runtime passes an injected resolver through.

**Step 2: Verify RED**

Run: `uv run pytest tests/integration/runtime/test_claude_runtime_fake_transport.py tests/unit/runtime/test_registry_runtime.py -q`
Expected: FAIL because runtime options ignore non-builtin tools.

**Step 3: Implement runtime wiring**

Resolve tools during runtime construction, set `tools`, `mcp_servers`, and `allowed_tools`, and reject unsupported subagent custom tools. Install an empty default resolver in the application composition root so unknown MCP IDs fail closed.

**Step 4: Verify GREEN**

Run the same targeted test command and expect PASS.

### Task 3: Add domain Agent init and validate CLI

**Files:**
- Create: `src/harness/cli.py`
- Modify: `pyproject.toml`
- Create: `tests/unit/test_cli.py`

**Step 1: Write failing CLI tests**

Cover valid initialization, generated files, no overwrite, invalid names, successful validation, invalid Manifest output, and stable non-zero exits.

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_cli.py -q`
Expected: FAIL because the CLI does not exist.

**Step 3: Implement the minimal CLI**

Use argparse with `agent init` and `agent validate`. Render a conservative template, reuse `publish_manifest`, and keep all output deterministic and secret-free.

**Step 4: Verify GREEN**

Run: `uv run pytest tests/unit/test_cli.py -q`
Expected: PASS.

### Task 4: Document the domain Agent golden path

**Files:**
- Modify: `README.md`
- Modify: `docs/local-development.md`
- Create: `docs/domain-agents.md`

Document the two-command scaffold flow, package layout, Python SDK MCP contract, MCP Registry ownership, model gateway reuse, publish/run flow, and the current pre-execution approval limitation.

### Task 5: Verify, audit, and continue

**Step 1: Run automated verification**

Run: `make verify && make web-test && COPILOTKIT_TELEMETRY_DISABLED=true make web-build`

**Step 2: Run a scaffold smoke**

Initialize a temporary domain Agent, validate it, publish it into the local API, and execute one Run through the current cc-switch/new-api path.

**Step 3: Audit safety and developer experience**

Inspect tool permission timing, approval state transitions, secret boundaries, subagent behavior, trace coverage, and scaffold ergonomics. Record concrete findings with file/line evidence.

**Step 4: Continue with the highest-risk finding**

Unless verification exposes a regression, implement the real SDK pre-execution permission bridge next, using a separate approved design and TDD plan.

