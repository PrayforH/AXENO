---
name: workspace-validation
description: Validate Harness workspace, tool, approval, artifact, and delegation behavior.
---

# Workspace validation workflow

Use this workflow for concrete Harness validation requests:

1. Identify whether the request is read-only, write-capable, delegated, or web-dependent.
2. Inspect before editing and keep every path inside the supplied workspace.
3. For a requested change, make the smallest useful edit and read it back.
4. Treat an approval pause or denial as an expected platform decision.
5. Report tool-backed evidence, changed paths, and any unfinished action.

Never turn a validation request into an unrelated demonstration of the Harness stack.
