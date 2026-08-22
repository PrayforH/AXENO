# public-opinion-agent

`public-opinion-agent@0.3.14` is the Codex edition of the evidence-backed Chinese
public-opinion Agent. Its Studio display name is `涉非舆情分析（Codex）`.

This package was not emitted unchanged by `harness agent init`. It is the worked
reference produced by adapting the earlier `public-opinion` behavior to the Codex loop.
The current version uses workspace evidence and Harness builtins only. It deliberately
does not declare external MCP, `Task`, Python tools or sub-Agents because those features
are outside the current Codex compiler contract.

Version notes:

- `0.3.13`: previous Claude Agent SDK release and rollback version; it has no Knowledge
  Base binding.
- `0.3.14`: current Codex release with a Codex-native prompt, Skill, tool boundary and
  model route; Knowledge Base references remain empty.

Validate and package:

```bash
uv run harness agent check agents/public-opinion-agent/agent.yaml --environment production
uv run harness agent pack agents/public-opinion-agent/agent.yaml
```

Before running it, bind `public-opinion-agent` to the
`codex-deepseek-v4-flash` route in Studio model management. Existing Sessions stay
pinned to the version and route snapshot created for them; create a new Session after a
version or binding change.
