# Input Artifacts and assistant-ui Migration Design

**Date:** 2026-07-13
**Status:** Approved

## Goal

Let a browser user attach local files to a message and let a Claude Agent SDK run read those files from its isolated workspace. Then replace the current CopilotKit chat surface with assistant-ui without weakening Harness execution, policy, observability, approval, or artifact semantics.

The browser remains an explicit-upload boundary. Arbitrary access to a user's local filesystem or folders is out of scope for the web application; that requires a separately trusted desktop/local-worker bridge later.

## Why this order

assistant-ui solves conversation rendering, composer behavior, attachments, and frontend runtime state. It does not upload a local file into the Harness object store, authorize it, or mount it into a Claude SDK workspace. Therefore the input-artifact lifecycle is implemented first and the UI migration consumes that stable contract.

## Options considered

### 1. First-class input artifacts — selected

Upload a file before run creation, return an opaque server-issued ID, reference that ID in the AG-UI message, and stage it into the run workspace.

Benefits:

- clear ownership and lifecycle before a run exists;
- no temporary or fake run is required;
- input and generated-output artifacts retain different semantics;
- retries can reuse uploaded bytes without sending base64 again;
- the server never accepts a browser-supplied local path.

### 2. Reuse run output artifacts with a provisional run

This saves a model but creates a run before the user submits, confuses input/output listings, and makes abandoned composer uploads hard to manage.

### 3. Put base64 directly in every AG-UI request

This is easy for a prototype but causes large streaming requests, duplicate transfers on retry, weak lifecycle controls, and event/log leakage risk.

## Backend model

`InputArtifact` is separate from the existing generated `Artifact`:

- `input_artifact_id`
- `tenant_id`
- `user_id`
- `name`
- `media_type`
- `status`
- `object_key`
- `sha256`
- `size_bytes`
- `created_at`

Only `READY` artifacts owned by the authenticated tenant and user can be attached. The existing `ArtifactStore` is reused because its storage contract is byte-oriented and its object key is keyed by tenant and opaque ID. A separate repository and service keep metadata semantics distinct.

Initial limits:

- maximum 10 files per run;
- maximum 25 MiB per file;
- maximum 100 MiB total per run;
- no automatic archive extraction;
- media type is recorded but does not grant execution privileges.

## API and AG-UI contract

`POST /v1/input-artifacts` accepts multipart form data and returns metadata including `input_artifact_id`.

The web BFF adds Harness identity headers and forwards uploads. Browser code never receives the Harness internal identity secret.

The composer represents an uploaded file as AG-UI `BinaryInputContent` or `DocumentInputContent`, with its server-issued input-artifact ID. `AguiRunService` extracts only opaque IDs produced by this API. URLs, inline bytes, and local paths are not treated as trusted workspace inputs.

The created `Run.input` contains:

```json
{
  "prompt": "Summarize the attached report",
  "input_artifact_ids": ["input_artifact_..."],
  "input_files": []
}
```

The final `input_files` paths are populated in the ephemeral runtime context after staging; raw file bytes are never written to durable events.

## Workspace staging

During `PROVISIONING`, before the runtime starts:

1. validate artifact ownership and readiness;
2. fetch bytes from the object store;
3. reduce every filename to a safe basename;
4. write `inputs/<short-id>-<safe-name>` below the provisioned workspace;
5. mark files read-only where the sandbox supports it;
6. emit metadata-only `input.staged` events;
7. pass the relative paths in `RuntimeContext.input_files`.

The Claude SDK runtime appends a short input inventory to the user prompt only when files exist. Because the SDK process uses the run workspace as `cwd`, normal SDK `Read` and permitted shell tools can access those relative paths.

Prefixing the filename with a stable fragment of the opaque ID prevents collisions and makes repeated staging idempotent. Path traversal never influences the destination directory.

## Failure and security behavior

- Invalid, missing, cross-user, cross-tenant, non-ready, oversized, or over-count input references fail before model execution.
- A staging failure follows the normal run failure path and records no file bytes in events.
- Upload content is not automatically executed, imported, or extracted.
- Workspace isolation remains the enforcement boundary; read-only file mode is defense in depth, not the primary boundary.
- A later garbage collector may remove unbound uploads by age. This is not required for the first local implementation but is part of the production lifecycle.

## assistant-ui migration

After the backend contract passes integration tests, replace the CopilotKit-specific frontend runtime with:

- `@assistant-ui/react` for thread, composer, attachment, markdown, and message primitives;
- `@assistant-ui/react-ag-ui` for the AG-UI runtime adapter;
- a same-origin Next.js AG-UI proxy that injects Harness identity server-side;
- a same-origin input-artifact upload proxy for composer attachments.

The visible application remains a full-page agent workspace, not a generic chat demo. The migration preserves:

- Harness run inspector and developer drawer;
- reasoning, tool-call, tool-result, sub-agent, approval, and artifact cards;
- formatted Markdown, JSON, and code with intentional copy/download controls;
- conversation reset and thread continuity;
- Langfuse-compatible trace/run identifiers.

Custom Harness activity is still derived from AG-UI custom events and run-event APIs. assistant-ui owns interaction primitives; Harness owns execution truth and domain-specific visualization.

## Acceptance criteria

1. A browser user can upload a local text file, submit a question, and the SDK reads the staged file.
2. A forged local path or another user's input artifact cannot be mounted.
3. Existing generated-artifact APIs and policy gates continue to pass.
4. The full-page UI uses assistant-ui and retains Harness-specific activity and approval surfaces.
5. Refreshing the browser does not create a duplicate run, and development hot reload is not presented as production behavior.
6. Python tests, web tests, production build, and a real cc-switch-backed file-reading smoke test pass.

