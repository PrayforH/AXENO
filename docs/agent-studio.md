# Agent Studio control plane

Agent Studio is an authoring and release control plane for domain Agents. It does not
introduce a second runtime format. A Studio draft is compiled into the same
`agent.yaml + prompt + Skills + evals` package accepted by the existing production
bundle gate and immutable `AgentVersion` registry.

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
- pinned sub-Agent versions;
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
