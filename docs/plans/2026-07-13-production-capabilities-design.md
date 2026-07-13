# Production Capabilities and Docker Deployment Design

**Date:** 2026-07-13

**Status:** Approved

## Objective

Turn the Phase 1 Claude Agent Harness into a deployable foundation for domain agents by:

1. fixing browser file upload;
2. resolving MCP credentials per tenant, user, project, and run;
3. adding a Daytona sandbox provider while retaining a self-contained local provider;
4. adding durable user memory;
5. preprocessing Office, PDF, text, and image inputs and exposing a thread file catalog;
6. allowing SDK agents to publish generated files as Harness artifacts; and
7. producing Docker images and a Compose deployment with optional Langfuse export.

The design deliberately keeps one agent loop. DeepAgents is not embedded into the
Claude Agent SDK runtime; reusable public-opinion assets are ported through Harness
ports, SDK MCP tools, prompts, and skills.

## Chosen Approach

Use a ports-and-adapters architecture around the existing Harness application layer.
Local development remains self-contained, while production infrastructure is selected
through settings and dependency injection.

Rejected alternatives:

- A minimal local-only implementation would not satisfy durable multi-process deployment.
- Embedding DeepAgents would duplicate session, checkpoint, approval, tool, trace, and
  filesystem semantics.

## Upload Failure and Fix

The assistant-ui adapter currently declares `accept: "*/*"`. assistant-ui's
`fileMatchesAccept` implementation treats only `"*"` as an unconditional wildcard.
For a text file, `"*/*"` reaches the media-family comparison and fails because the file
MIME type does not begin with `"*/"`. The Composer therefore rejects the file before
calling the custom adapter. No BFF or Harness upload request is made.

The fix will:

- use the assistant-ui wildcard contract (`accept: "*"`);
- surface upload progress and errors in the Composer;
- retain server-issued opaque input artifact IDs as the only data sent with a message;
- test the Composer-to-adapter boundary, not only the adapter in isolation; and
- verify the full browser flow with a fixture containing a unique marker.

## Runtime Context

Every run receives an immutable `ExecutionContext` containing:

- tenant ID;
- user ID;
- optional project ID;
- agent name and version;
- session and run IDs; and
- trace context.

Infrastructure adapters receive this context explicitly. Context variables may be used
inside synchronous SDK tool callbacks, but they are populated and reset at the run
boundary so concurrent runs cannot leak identity or credentials.

## Dynamic MCP Credentials

`DynamicMcpCredentialProvider` resolves credentials for a logical MCP registration at
run time. A Manifest contains only the logical MCP ID and never contains credentials.

The provider returns an allowlisted set of headers and environment variables. Initial
implementations support:

- request-scoped credential passthrough supplied by a trusted server-side BFF/header;
- server-managed secret references; and
- an empty provider for local and test runs.

Resolved secrets are held only for the execution and are excluded from events, logs,
workspace snapshots, prompts, and trace attributes. Redaction is applied at the runtime
event boundary as defense in depth.

## Sandbox and Workspace Lifecycle

`HARNESS_SANDBOX_PROVIDER=local|daytona` selects an implementation of the existing
`SandboxProvider` port.

### Local provider

The local provider is the default Docker profile and remains fully self-contained. It
uses a managed workspace root rather than an untracked arbitrary browser path.

### Daytona provider

The production profile connects to an external Daytona service using the async Python
SDK. Sandboxes are labeled with tenant, user, project, and session identifiers. The
provider can create or retrieve the session sandbox, start it when necessary, expose a
workspace facade, and apply stop/archive/delete policies.

Daytona is intentionally not emulated inside Compose. The deployment contains the
Harness services and supplies Daytona connection settings for production.

### Workspace restore

Before input staging, the orchestrator restores the most recent session workspace
snapshot when `restoreSession` is enabled. At successful or policy-approved terminal
states, it archives the workspace when `archiveOnComplete` is enabled. Snapshot metadata
is stored durably and object bytes live in the artifact object store.

## User Memory

`UserMemoryRepository` stores one versioned document per `(tenant, user, agent)`.
PostgreSQL is authoritative; an in-memory adapter supports unit tests.

At run start, a bounded memory projection is injected ahead of the current user task.
The SDK exposes an `update_user_memory` MCP tool that performs optimistic concurrency
updates. Memory content is not emitted in normal events or traces. The API supports
future read, disable, and erase operations without changing the runtime contract.

## Input Processing and File Catalog

The original upload remains immutable. `InputProcessor` creates derived artifacts and a
catalog entry with parent/child lineage.

Initial processors:

- text, Markdown, CSV, JSON, and XML: normalized text and metadata;
- DOCX: Markdown, headings, tables, and extracted images;
- XLSX: workbook summary plus Markdown/CSV projections per worksheet;
- PPTX: slide outline, speaker notes when present, and extracted images;
- PDF: page-aware Markdown/text plus metadata; and
- images: validated original plus dimensions and format metadata.

OCR is not enabled by default. Unsupported files remain available as immutable originals
with an explicit `unsupported` processing result.

The thread file catalog is scoped by tenant, user, and session. A run mounts deterministic
paths such as:

```text
inputs/original/report.docx
inputs/processed/report/report.md
inputs/processed/report/outline.json
```

## Publishing Output Artifacts

`publish_artifact` is an SDK MCP tool created for each run. It accepts a workspace-relative
path and optional display metadata.

The tool:

1. resolves the path beneath the active workspace;
2. rejects traversal, symlink escape, directories, and oversized files;
3. reads the file through the sandbox workspace facade;
4. stores bytes through `ArtifactService`;
5. records SHA-256, MIME type, size, and run ownership; and
6. emits the existing artifact event consumed by AG-UI and assistant-ui.

The UI renders a download/preview card using the Harness artifact ID. It never trusts a
model-supplied external URL as an owned artifact.

## Persistence and Production Composition

The production composition root uses PostgreSQL repositories for agents, sessions, runs,
events, approvals, input artifacts, output artifacts, memory, workspace snapshots, and
the file catalog. Redis provides the task queue/event wakeups and MinIO provides object
storage.

The local/test composition remains available but production mode must fail fast if a
required durable adapter is missing.

## Observability and Langfuse

The application emits OpenTelemetry spans for API requests, queue time, input processing,
workspace restore/archive, sandbox lifecycle, model runs, MCP resolution/calls, memory,
and artifact publication.

Docker includes an optional OpenTelemetry Collector profile. It exports OTLP/HTTP to a
configured Langfuse `/api/public/otel` endpoint. Raw secrets, file contents, user memory,
and full prompts are excluded by default. Stable tenant/user hashes may be used for
correlation without exposing raw identifiers.

## Docker Topology

The deployable Compose stack contains:

- `api`;
- `worker`;
- `web` (Next.js standalone output);
- `migrate`;
- PostgreSQL;
- Redis;
- MinIO and bucket initialization; and
- an optional OpenTelemetry Collector profile.

Images use multi-stage builds, non-root runtime users, health checks, and explicit
configuration. `.env.docker.example` documents local and Daytona profiles. The default
profile uses the local sandbox; the production profile enables Daytona settings.

## Error Handling

- Upload and processor failures preserve the immutable original and expose structured
  error codes.
- A missing MCP credential fails before the model can call the server.
- Sandbox provisioning and restore failures terminate the run with a durable event.
- Memory conflicts retry a bounded number of times and otherwise return a tool error.
- Artifact publication failures never manufacture a successful download card.
- Worker retries are idempotent through run state, fencing tokens, and stable artifact
  ownership.

## Verification

Automated verification must cover:

- browser selection of a real file and visible Composer attachment state;
- BFF upload and SDK read of the fixture's unique marker;
- credential isolation across concurrent users and redaction from events;
- Local and mocked Daytona sandbox contract behavior;
- workspace archive followed by restore in a later run;
- cross-session memory injection and concurrent update protection;
- fixtures for DOCX, XLSX, PPTX, PDF, text, and image processing;
- thread file catalog ownership and lineage;
- generated workspace file publication, download, and hash validation;
- OTel export configuration without leaking protected fields; and
- `docker compose build`, healthy startup, migrations, and containerized end-to-end flow.

Optional external smoke tests cover a real Daytona service, real new-api model gateway,
and a real Langfuse endpoint when credentials are supplied.

