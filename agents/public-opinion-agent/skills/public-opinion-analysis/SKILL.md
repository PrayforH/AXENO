---
name: public-opinion-analysis
description: Analyze public-opinion evidence, source quality, narratives, propagation, and operational risk without inventing metrics.
---

# Public-opinion analysis workflow

Use this Skill when the user asks for舆情监测、事件复盘、风险研判、观点聚类或舆情报告。

1. Establish the scope: subject, event, time window, geography/language and requested deliverable.
2. Build an evidence ledger. Capture source type, publisher, URL, publication time, retrieval time and whether it is independent or derivative.
3. Normalize claims into events. Merge reposts and near-duplicates; do not count duplicated syndication as independent confirmation.
4. Separate factual claims, attributed opinions, analyst inference and unresolved uncertainty.
5. Use at least two independent credible sources for a material factual claim when available. Otherwise mark it as single-source or unverified.
6. Cluster narratives and positions without claiming statistical representativeness unless the dataset and sampling method support it.
7. Apply the risk rubric in `references/risk-rubric.md` and state both escalation and de-escalation signals.
8. Produce the report schema in `references/report-contract.md` with full source URLs.

## Delegation

Delegate bounded evidence-reading tasks to `helper-agent`, such as extracting a timeline from uploaded files. Give the sub-Agent an explicit file scope and requested output. The main Agent remains responsible for source quality, cross-checking and the final risk judgment.

## Non-goals

Do not perform social posting, moderation, deletion, account lookup, doxxing or outreach. Do not manufacture sentiment percentages, reach, trends or “whole internet” coverage from an unrepresentative sample.
