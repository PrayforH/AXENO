---
name: general-task-orchestration
description: Turn a general user request into a scoped, tool-backed and verifiable result without assuming a business domain.
---

# General task orchestration

Use this workflow for requests that do not already have a more specific business Agent:

1. Restate the concrete outcome internally and identify the evidence needed to prove completion.
2. Inspect the supplied context and workspace before deciding whether a question is necessary.
3. Choose only tools that are actually available in the current Run.
4. Execute the smallest safe set of actions that satisfies the request.
5. Verify outputs, distinguish observed facts from inference, and report unresolved inputs.

When a request requires domain data, credentials, or a specialized workflow that is not available, stop at the honest boundary and explain which Agent or MCP capability is needed. Do not simulate an unavailable business system.
