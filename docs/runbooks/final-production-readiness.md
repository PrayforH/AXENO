# Final production readiness checklist

## Automated gates

- [ ] Ruff, Pyright and the complete Python suite pass with PostgreSQL, Redis and MinIO.
- [ ] Web tests and production build pass.
- [ ] Alembic has one head; empty upgrade and latest-revision downgrade/re-upgrade pass.
- [ ] All Agent packages pass production checks and produce byte-identical archives twice.
- [ ] Fake runtime smoke covers approval, resume, artifact hash and AG-UI terminal event.
- [ ] Eval, quality, promotion, rollback, Session pinning, CAS, tenant isolation and lifecycle tests pass.
- [ ] API, Web and Sandbox images have no unwaived fixed HIGH/CRITICAL vulnerability.
- [ ] Release manifest, image signatures, SBOM attestations and BuildKit provenance verify.
- [ ] Promotion uses the same release ID, bundle hashes and image digests in all environments.

## Live acceptance

- [ ] A member logs in and creates an Orchestrator draft with reviewed model route, Tavily, policy and
      three pinned Sub Agents.
- [ ] Concurrent draft edit returns a revision conflict and does not overwrite the other writer.
- [ ] Preview proves model streaming/tool use, isolated Sandbox, MCP, approval and Artifact collection.
- [ ] happy/ambiguous/safety Eval cases have inspectable durable evidence.
- [ ] An admin publishes the immutable bundle and promotes test → canary → production.
- [ ] Lead delegates parallel work, returns a cited result and produces a downloadable report.
- [ ] Bash approval survives refresh; reject, expiry, cancel and Worker restart converge correctly.
- [ ] Each Run is one Langfuse trace, one Session groups the conversation and Scores carry version and
      Deployment identity.
- [ ] A deliberately failing canary stops production and restores the prior snapshot/image release.
- [ ] Tenant isolation, secret redaction, quota exhaustion, export/delete and audit are verified.
- [ ] Desktop and mobile browser checks cover chat, Studio, settings/memory and artifact download.

Every checked item needs a command, workflow URL, API response, trace, screenshot or audit ID. “Looks
correct in code” is not evidence.

## Custom role decision

User-defined roles are deliberately not part of the current release. The platform keeps audited,
versioned built-in roles (`member`, `admin`, service identity) and permission checks at every API. A
custom-role editor would introduce role lifecycle, tenant delegation, privilege-escalation analysis,
approval, migration and emergency-access requirements that are not justified by the current use cases.

Add custom roles only after at least two tenants require materially different permission bundles. The
future design must store immutable role revisions, prevent grant above the actor's own permissions,
show effective permissions before save, require dual approval for publish/deploy/secret permissions and
preserve old audit interpretation after a role changes. Until then, new exceptions become explicit API
permissions and reviewed built-in role changes, not arbitrary UI configuration.
