---
name: case-skill-search
description: |
  通用类案分析 POC 的 Skills 化检索 skill，内置默认知识库。
  当需要根据结构化检索语句检索类案原文、查找证据片段、比较多个样本、提取影响因素/原因/结果/争议点，或为分析结论提供 case_id/chunk_id 引用时必须使用。
  本 skill 以自身目录下的 knowledge_base 作为默认 KB，使用规则和关键词匹配，不使用向量检索、embedding 或向量数据库。
---

# case_skill_search

## 作用

执行通用 Skills 化检索，从本 Skill 内置的默认知识库召回类案原文证据片段。

本 Skill 用于连接“结构化检索语句”和“原文证据召回”。它不依赖任何特定语料、行业或业务领域；检索时默认读取当前 Skill 目录下的 `knowledge_base/`。

## 默认知识库位置

默认 KB 固定为本 Skill 内部目录：

```text
.claude/skills/case-skill-search/knowledge_base
```

相对当前 Skill 目录为：

```text
./knowledge_base
```

`knowledge_base` 用于存放可检索的类案材料、切片结果、索引文件或其他可召回证据数据。执行检索时应优先读取该目录中的内容，不应把 `output` 作为知识库目录。

当前默认 KB 可包含：

- `case_skill_index.generated.json`：由本地 harness 或交付流程生成的 Skills 化检索索引与原文切片；
- 其他可检索类案材料、切片结果或证据数据文件。

知识库中的每条可召回证据建议包含：

- `case_id`：类案唯一标识；
- `title`：类案标题或名称；
- `metadata`：结构化元数据；
- `chunk_id`：原文片段唯一标识；
- `text`：原文片段内容。

## 什么时候使用

当用户需要：

- 检索类案；
- 查找原文证据；
- 比较多个样本；
- 提取影响因素、原因、结果或争议点；
- 为分析结论提供 `case_id/chunk_id` 引用；

都应使用本 Skill，并从内置默认 KB 中召回证据。

## 输入格式

```json
{
  "queries": [
    {
      "query_id": "Q1",
      "step_id": "S1",
      "intent": "factor_extract",
      "filters": {},
      "keywords": ["因素", "结果"],
      "top_k": 5
    }
  ]
}
```

支持的通用 intent：

- `case_scope_filter`
- `issue_filter`
- `result_filter`
- `factor_extract`
- `reason_extract`
- `compare_cases`
- `evidence_lookup`

## 输出格式

```json
{
  "results": [
    {
      "query_id": "Q1",
      "matched_skill": "factor_evidence_lookup",
      "case_id": "case_001",
      "chunk_id": "case_001_chunk_0001",
      "title": "样本标题",
      "metadata": {},
      "score": 0.86,
      "matched_reason": "意图=factor_extract；关键词=因素",
      "text": "召回的原文片段"
    }
  ]
}
```

## 检索规则

1. 以本 Skill 的 `./knowledge_base` 作为默认且优先的检索知识库。
2. 根据 `intent` 匹配 `.claude/skills/case-skill-index/index.json` 中的通用规则。
3. 根据 `filters.case_titles` 可选限制类案范围。
4. 在知识库材料的标题、元数据和正文切片中进行关键词子串匹配。
5. 使用通用增强词进行轻量加权排序。
6. 返回原文片段、来源元数据、命中规则、匹配原因和排序分。

## 约束

- 不把 `similar-case-analysis-poc/output` 作为平台检索知识库。
- 不依赖独立的 `knowledge_base` Skill；默认 KB 已合并进本 Skill。
- 不使用向量检索。
- 不使用语义 embedding。
- 不使用向量数据库。
- 不根据常识补全证据。
- 检索结果必须保留原文 `text`。
- 最终分析结论必须能追溯到 `case_id/chunk_id`。
