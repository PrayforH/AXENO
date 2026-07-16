# Production Agent Scaffold Design

**Date:** 2026-07-16

**Status:** Implemented and verified

## Objective

Make Phase 1 a reusable foundation for production domain Agents. A new Agent should be
created from a safe template, customized through prompts, Skills and tools, checked by
deterministic production gates, evaluated from a versioned dataset, packaged
reproducibly, and executed with the permission policy declared by its immutable
Manifest snapshot.

## Product boundary

The Harness remains the runtime/data plane. It owns identity, Session/Run/Event,
approval, Sandbox, workspace, artifacts, model routing and observability. A domain Agent
package owns only business behavior:

```text
agent.yaml
prompts/system.md
skills/<skill>/SKILL.md
tools/
evals/suite.yaml
README.md
```

The scaffold does not add another visual Agent builder or duplicate Langfuse. It makes
the code-first package contract strong enough for a future NAC or other control plane to
consume.

## Package templates

`harness agent init` supports three profiles:

- `analyst`: read-only evidence gathering; the default and safest starting point;
- `operator`: workspace write/edit plus reviewed shell execution; and
- `orchestrator`: analyst capabilities plus explicit sub-Agent delegation.

Every profile generates a valid Manifest, structured system prompt, one discoverable
Skill, a three-path evaluation suite (happy, ambiguous, safety), tool extension guidance
and a package README. Generated placeholders are intentionally rejected by the
production readiness check until the developer supplies real domain content.

## Immutable Skills

Manifest Skill entries are package-relative directories. Publication parses each
`SKILL.md`, validates its frontmatter, snapshots every regular file as base64 with a
content hash, and rejects symlinks, traversal, duplicate names and oversized assets.
Runtime materializes the immutable snapshot under `.claude/skills/<name>` and passes
Skill names—not source paths—to Claude Agent SDK. This prevents post-publication file
changes from altering an existing Agent version.

For Daytona, materialization occurs before `SandboxProvider.prepare`, so the exact
snapshot is uploaded with the workspace before the remote Claude CLI starts.

## Permission profiles

The Manifest policy ID selects a server-owned profile. Built-in profiles are:

- `production-read-only`;
- `production-standard`; and
- `production-orchestrator`.

`local-standard` remains as a backward-compatible alias. Unknown profile IDs fail closed
before a tool executes. The Manifest cannot provide policy rules or grant itself more
authority.

## Production check

`harness agent check <manifest> --environment production` verifies:

- semantic, immutable version references;
- non-placeholder domain metadata and prompt sections;
- model streaming/tool-use capabilities and a finite budget;
- valid immutable Skills;
- declared tools compatible with the selected profile;
- workspace archive/restore settings;
- an evaluation suite with happy, ambiguous and safety coverage; and
- absence of secret-like files, symlinks and unsafe package paths.

The command returns a non-zero exit code for blocking findings and supports JSON output
for CI.

## Evaluation contract

`evals/suite.yaml` declares versioned cases with prompt, tags, expected terminal states,
required/forbidden tools, approval expectations and output assertions. Static validation
is always available. A live runner can publish or target a fixed Agent version, create an
isolated Session per case, replay durable events, and emit JSON/JUnit-compatible results.
No model-based judge is required for the deterministic first layer.

## Reproducible bundle

`harness agent pack` runs the production check and creates a deterministic ZIP with
fixed timestamps, sorted paths and a `bundle.json` provenance record. Secrets, symlinks,
caches, build output and oversized files are rejected. Provenance stores two identities:
a runtime content hash for Manifest, prompt and immutable Skills, and a full package hash
that also covers evals, fixtures and docs. Changing evaluation evidence therefore cannot
silently reuse the same published version.

## Runtime limits and telemetry

`timeoutSeconds` is enforced around the full Claude SDK execution and maps expiration to
the distinct `timed_out/runtime_timeout` Run outcome. Model spans include safe package,
route, policy, latency, turn, cost and aggregate Token-count attributes. Usage is an
explicit numeric allowlist; raw prompts, responses and provider usage dictionaries are
never exported.

## Verification

Completion requires focused unit/integration tests, full Pytest, Ruff, Pyright, frontend
tests/build, deterministic bundle comparison and a local fake-runtime lifecycle using a
generated domain package. External model, Daytona and Langfuse smoke tests remain
explicitly opt-in and must be reported as skipped when credentials are absent.
