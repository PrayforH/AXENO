# Agent Studio control plane

Agent Studio is an authoring and release control plane for domain Agents. It does not
introduce a second runtime format. A Studio draft is compiled into the same
`agent.yaml + prompt + Skills + evals` package accepted by the existing production
bundle gate and immutable `AgentVersion` registry.

The cross-platform production-line comparison and the reasons behind these boundaries
are recorded in [`agent-production-line-benchmark.md`](agent-production-line-benchmark.md).
The complete Chinese platform design, including architecture, runtime, security,
multi-agent collaboration, evaluation and delivery phases, is recorded in
[`agent-production-platform-design.md`](agent-production-platform-design.md).

## Current parallel-work boundary

This branch intentionally avoids the authentication and Langfuse workstream:

- the standalone router in `harness.studio.api` is not mounted in the main FastAPI app;
- it accepts only an authenticated `StudioActor` already placed on `request.state`;
- there is no fallback identity header or unauthenticated local user;
- the draft repository is in-memory and no migration number is claimed;
- the `/studio/agents` page marks publication as pending authentication/RBAC;
- no Langfuse or OTel configuration is changed.

After the authentication branch lands, the integration layer should map its verified
principal to `StudioActor`, require a `builder` role for reads/edits and a `publisher`
role for publication, mount the router, and replace the in-memory repository with a
tenant-scoped PostgreSQL adapter.

## Authoring contract

A draft contains:

- logical model route and model name;
- structured System Prompt;
- immutable Skill source and text assets;
- reviewed builtin tool names and logical MCP references;
- pinned sub-Agent versions with role aliases, delegation descriptions and background mode;
- server-owned permission Profile;
- workspace lifecycle and finite limits;
- happy, ambiguous and safety evaluation cases.

The draft compiler performs two gates:

1. catalog validation rejects unknown model routes, models, builtin tools, MCP
   references and permission Profiles;
2. the existing production package checker validates Prompt sections, Skills, eval
   coverage, policy/tool compatibility, paths, file sizes, secrets and reproducibility.

Successful compilation produces the existing deterministic ZIP bundle. Publishing uses
`AgentService.publish_bundle`; Studio does not write `AgentVersion` rows directly.

## Lead and Sub Agent collaboration

The supported production shape is a fixed one-level delegation graph: one Lead Agent is
the only user-facing coordinator and delegates bounded work through the SDK `Task` tool.
Each Sub Agent binding has a stable role alias, a pinned reusable Agent version, a concise
responsibility contract and an optional background flag:

```yaml
subagents:
  - ref: helper-agent@1.0.0
    alias: fact-checker
    description: Verify claims and return source-backed findings.
    background: true
  - ref: helper-agent@1.0.0
    alias: risk-reviewer
    description: Challenge conclusions and identify uncertainty.
    background: true
```

Multiple role aliases may reuse the same immutable Agent version. The alias and
description are passed to Claude Agent SDK so the Lead can choose the right specialist;
background-enabled roles may run concurrently when the Lead emits independent tasks.
The Lead remains responsible for checking returned evidence and synthesizing the final
answer.

Sub Agents keep their own Prompt, Skills, builtin tools, permission Profile and turn
limit. The parent Run budget and wall-clock timeout remain the outer hard limits. The
current runtime intentionally supports only one delegation level and builtin tools on
Sub Agents; MCP and Python tools stay on the Lead until per-Sub credential, network and
artifact isolation are implemented. Lead and Sub Agents share the Run workspace, so the
Lead can collect external evidence first and delegate analysis over those files.

## Sandbox and network policy

Production isolation is mandatory and is not authored as an on/off switch. The Agent
draft always emits:

```yaml
workspace:
  mode: isolated
```

Domain builders declare required capabilities. Platform administrators bind deployment
execution Profiles to Daytona, gVisor or another reviewed backend. A future
`executionProfile` may select among stronger platform-managed isolation classes, but it
must never allow a domain builder to disable isolation or supply a raw provider config.

Network access is capability-specific:

- no registered network MCP means no declared network capability;
- `tavily-readonly` means controlled external MCP egress for search and extraction;
- it does not allow arbitrary `curl`, Bash networking or arbitrary MCP URLs;
- credentials remain server-owned and are never stored in a draft or bundle.

Selecting an external MCP adds a deployment warning. Before rollout, the platform must
verify credentials, MCP initialization and `tools/list`, and reachability from the
actual Sandbox rather than only from the API host.

## Standalone API contract

The unmounted router defines:

```text
GET  /v1/studio/capabilities
GET  /v1/studio/drafts
POST /v1/studio/drafts
GET  /v1/studio/drafts/{draft_id}
PUT  /v1/studio/drafts/{draft_id}
POST /v1/studio/drafts/{draft_id}/validate
GET  /v1/studio/drafts/{draft_id}/bundle
POST /v1/studio/drafts/{draft_id}/publish
```

Draft replacement uses an expected revision and rejects stale writes. Every repository
operation is tenant-scoped. Publication records the immutable version and content hash
back on the draft after the existing release service succeeds.

## Integration order

1. Merge authentication/RBAC and Langfuse changes into the target branch.
2. Rebase this branch and resolve only composition/layout integration points.
3. Add a PostgreSQL draft repository using the next available migration revision.
4. Mount `harness.studio.api.router` and map the authenticated principal to
   `StudioActor`.
5. Replace the static model/MCP catalog with repositories backed by server-reviewed
   registrations and secret references.
6. Wire `/studio/agents` to the API and enable Publish only for authorized publishers.
7. Add deployment preflight jobs and live eval results; surface Langfuse version metrics
   without changing the runtime event contract.
