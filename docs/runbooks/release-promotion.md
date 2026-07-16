# Release and environment promotion runbook

## Purpose

This runbook promotes one immutable Harness release through `test → canary → production` without
rebuilding. A release consists of three digest-pinned images, reproducible Agent bundles, three SBOMs,
a canonical `release-manifest.json`, Sigstore signatures and SBOM attestations.

The workflow intentionally has no operations page dependency. GitHub protected environments are the
human authorization boundary; the Harness Deployment/Eval/Quality APIs are the runtime gate.

## One-time deployment runner setup

Register a Linux runner with labels `self-hosted`, `linux`, `harness-deploy`. Create protected GitHub
environments named `test`, `canary`, and `production`; require reviewer approval for production.
Configure these environment values:

| Kind | Name | Meaning |
| --- | --- | --- |
| variable | `HARNESS_DEPLOY_ENV_FILE` | Absolute path to a pre-provisioned, mode-0600 Compose env file |
| variable | `HARNESS_RELEASE_STATE_ROOT` | Durable writable directory for `current/previous/failed` manifests |
| variable | `HARNESS_BASE_URL` | Control-plane URL reachable from the runner |
| variable | `HARNESS_WEB_URL` | Web URL reachable from the runner |
| variable | `HARNESS_TENANT_ID` | Release tenant |
| variable | `HARNESS_EXECUTION_PROFILE` | Production-approved isolated profile, normally `isolated-default` |
| secret | `HARNESS_API_BEARER_TOKEN` | At least 32 random characters; never put it in workflow inputs |

The Compose env file contains target-specific secrets. It is never uploaded, echoed, copied into the
release artifact or passed to a Sandbox. The runner needs Docker/Compose, write access to the release
state directory, read access to the env file and network access to GHCR, the Harness API and Web.

## Build once

Run `.github/workflows/release.yml` for an exact commit. The workflow first calls the complete reusable
CI workflow, then:

1. builds API, Web and Sandbox images exactly once with BuildKit provenance and SBOM enabled;
2. blocks HIGH/CRITICAL fixed vulnerabilities;
3. packs every Agent twice and compares archive bytes;
4. writes SPDX JSON SBOMs and a canonical manifest containing every bundle and image hash;
5. keyless-signs each image, attaches each SBOM as an attestation and signs the manifest blob;
6. uploads `release-<commit>` as the only promotion input.

Record the release workflow run ID and source commit. Never promote a local directory or a mutable tag.
The Trivy scan uses a signed scanner image rather than a mutable third-party Action because Aqua's 2026
incident explicitly recommends full-SHA Action pinning and signature verification:
[Aqua advisory](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23).

## Promote in order

Run `.github/workflows/promote.yml` with the release run ID, source commit and `test`. Repeat with
`canary`, then `production` only after the previous job and its observation window are accepted.

At every environment the workflow:

1. checks out the exact source commit and downloads `release-<commit>`;
2. verifies the manifest Sigstore identity, canonical release ID, bundle hashes, SBOM hashes and image
   signatures;
3. pulls exact `reference@sha256:digest` images, runs the forward migration, starts services with
   `--no-build`, waits for health and runs the idempotent seed;
4. uploads the exact Agent bundles and verifies the server-returned manifest/package hashes;
5. evaluates offline Eval and online Quality gates;
6. checks that canary was already proven in test, and production in canary, with the same release ID,
   Agent version/package hash and Sandbox image digest;
7. promotes using environment revision CAS and waits for a durable `succeeded` terminal state;
8. runs API/Web black-box health checks.

`canary` defaults to 10% and only affects new Sessions. Existing Sessions remain pinned to their
original Deployment Snapshot. Concurrent promotion to the same environment is serialized by GitHub and
still protected by Harness environment revision CAS.

## Acceptance evidence

Retain the workflow URL, source commit, `releaseId`, image digests, bundle hashes, environment snapshot
IDs, Eval/Quality gate response and final health result. Do not retain the service token or env file.
The release artifact retention is 90 days; production evidence that must outlive it should be copied to
the organization's approved immutable audit store.
