---
name: delegated-investigation
description: Perform bounded, read-only investigation for a parent Agent.
---

# Delegated investigation workflow

1. Keep the parent Agent's question as the only scope.
2. Locate the minimum relevant workspace records with Glob or Grep.
3. Read the source records and cite their paths.
4. Separate facts, inference, and missing evidence.
5. Return a concise recommendation without taking external or write actions.
