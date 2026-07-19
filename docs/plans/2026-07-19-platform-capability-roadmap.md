# Agent Studio platform capability roadmap

**Branch:** `feature/platform-capability-roadmap`

**Goal:** evolve Agent Studio from a governed Agent build-and-run workbench into a
reusable organizational Agent platform without weakening immutable releases, deterministic
policy enforcement, sandbox isolation, durable Runs, evaluations, or promotion gates.

## Product principles

1. One published Agent version may be invoked from multiple channels, but every invocation
   converges on the existing `Session -> Run -> Event -> Artifact` contract.
2. Deployment environments remain the authority for selecting an immutable Agent snapshot.
   Triggers never point at `latest`.
3. Tools may be discovered lazily only inside a versioned, server-reviewed capability set.
4. User and workload credentials are resolved at execution time and never stored in Agent
   bundles, trigger records, prompts, events, or browser configuration.
5. Knowledge retrieval is permission-filtered before ranking and always returns inspectable
   source references.
6. Policy decisions stay deterministic. LLMs may suggest policies but cannot be the final
   enforcement mechanism.
7. Every asynchronous action is idempotent, cancellable where meaningful, auditable, and
   attributable to tenant, user/workload, Agent, environment, deployment snapshot and Trace.

## Target architecture

```mermaid
flowchart LR
    CHAT["Task chat"] --> ROUTER["Invocation router"]
    WEBHOOK["Webhook / A2A"] --> ROUTER
    SCHEDULE["Schedules"] --> ROUTER
    CHATOPS["Slack / email"] --> ROUTER

    ROUTER --> ENV["Environment resolver"]
    ENV --> SESSION["Session"]
    SESSION --> RUN["Durable Run"]
    RUN --> TOOLS["Versioned tool catalog"]
    RUN --> KNOWLEDGE["Permission-aware knowledge"]
    RUN --> POLICY["Call + result policies"]
    RUN --> TRACE["Unified execution trace"]

    ENV --> SANDBOX["Sandbox and egress profile"]
    ENV --> CREDENTIALS["Workload / user credentials"]
    ENV --> QUOTA["Scoped quota and cost"]
```

## Delivery phases

### Phase 1 — published Agent triggers

Deliver a reusable invocation surface over the current production runtime.

- Tenant-scoped Trigger records bound to `agent_name + environment`.
- Webhook trigger creation, list, enable/disable and secret rotation.
- High-entropy secrets returned once; only SHA-256 digests are persisted.
- Public invocation endpoint protected by the trigger secret.
- Required `Idempotency-Key`; retries converge on one Session and Run.
- Environment resolution pins the current deployment snapshot when the Session is created.
- Trigger invocation reuses Run admission, queueing, streaming events, cancellation,
  approvals, artifacts, quality hooks and observability.
- Trigger actor is a workload identity (`trigger:<trigger_id>`), not an impersonated user.
- Studio shows endpoint, state, environment, last invocation and one-time secret handoff.

Acceptance:

- an enabled trigger with a valid secret creates one queued Run;
- the same idempotency key and payload returns the same Session and Run;
- the same key with a different payload fails closed;
- disabled triggers and invalid secrets return indistinguishable authorization failures;
- an environment without a healthy deployment cannot be invoked;
- secret rotation immediately invalidates the old secret;
- no plaintext secret appears in persistence or API list responses;
- memory and PostgreSQL repositories pass equivalent contract tests.

### Phase 2 — environment resource boundaries

Promote Environment from a deployment route into a platform boundary:

- versioned execution/network profile;
- allowed model routes and capability catalog revision;
- allowed MCP and knowledge resources;
- credential scope;
- quota/cost policy;
- immutable environment snapshot attached to each Session.

Acceptance:

- Environment policy updates use Environment revision CAS and increment a separate
  `policyRevision`;
- a policy is rejected when its capability catalog revision, Execution Profile version,
  network profile, model routes or MCP references are not currently reviewed;
- promotion is rejected when the published Agent requires resources outside the target
  Environment policy;
- policy changes cannot make an active deployment invalid; operators first deploy a
  compatible version, then narrow the policy;
- every environment-bound Session stores the complete policy, hash, policy revision and
  Environment revision that were effective at creation;
- later Environment changes do not alter an existing Session snapshot;
- runtime model and MCP resolution is checked again against the Session snapshot;
- user and workload Sessions fail closed when their credential scope is not allowed;
- run budget, model tokens and Artifact bytes use the stricter Environment ceiling.

### Phase 3 — load tools when needed

Detailed design: [Phase 3 — versioned tool directory and load-on-demand](./2026-07-19-versioned-tool-directory.md).

- Publish a canonical, hash-bound tool-directory snapshot with each new Agent version.
- Keep built-in workspace tools eager and defer reviewed MCP schemas with Claude CLI's
  native Tool Search path.
- Search only the immutable directory whose Catalog revision is accepted by the target
  Environment.
- Require the runtime MCP allowlist to exactly match the published directory before the
  model request starts.
- Invoke the selected tool by its real name so target policy, approval, credential,
  quota, trust and audit controls remain authoritative.
- Fail closed when the route lacks `tool_search`, the directory is missing or tampered,
  or runtime registrations are wider or narrower than the published snapshot.

### Phase 4 — governed knowledge sources

- Detailed design:
  [Phase 4 — governed knowledge sources](./2026-07-19-governed-knowledge-sources.md).
- Knowledge bases, connectors, checkpointed incremental sync and source health.
- File/web first, then GitHub and enterprise connectors.
- Permission filtering before retrieval, hybrid search, reranking and citations.
- Knowledge results classified through the existing trust-state model.

### Phase 5 — delegated credentials and policy control plane

- Personal, team and workload connection scopes.
- Short-lived credential leases and revocation.
- Separate tool-call and tool-result policy authoring.
- Policy simulator, impact preview, matched-rule explanation and audited publication.

### Phase 6 — platform operations and interoperability

- In-product Lead/Sub execution graph with latency, token, cost and failure attribution.
- Organization/team/user/Agent/environment/key budgets and alerts.
- A2A Agent Cards and streaming task interoperability.
- Scheduled and chat-ops triggers.
- Guarded platform-management MCP for administrative automation.

## Explicit non-goals

- No automatic access to every tool visible to a user.
- No mutable `latest` deployment binding.
- No arbitrary MCP URL or credential in a draft.
- No plaintext trigger secret recovery.
- No nested delegation until per-Sub identity, credential, network, Artifact, cost and
  cancellation propagation are proven.
- No Kubernetes MCP orchestration requirement for the first four phases.

## Migration and rollback

Phase 1 adds `agent_triggers`. It contains public metadata and a one-way secret digest.
Rollback disables the public route first, then drops the table through the Alembic downgrade.

Phase 2 is an additive JSON-envelope migration: existing Environment and Session rows remain
readable through model defaults, while newly created Environment records and Sessions include
resource policies and immutable snapshots. No table rewrite is required. Rolling back Phase 2
stops writing the new fields; older binaries ignore the additional JSON keys only after an
explicit compatibility downgrade that strips them from active records.
