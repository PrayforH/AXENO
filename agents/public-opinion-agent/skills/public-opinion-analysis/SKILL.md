---
name: public-opinion-analysis
description: 面向中文舆情监测、专用舆情数据查询、事件复盘、观点与传播分析、风险研判及 HTML 或 Markdown 报告生成；在用户要求构造舆情关键词、地域/排除条件、热搜分析、原文链接或可下载舆情报告时使用。
---

# 舆情分析工作流

1. 明确主体、事件、绝对时间窗、地域、语言、排除项、数据范围与交付形式。只有缺失项会改变查询或结论时才追问。
2. 选择最窄的数据路径：用户材料 → 当前工作区内的可验证证据。不要用模型记忆或局部样本冒充专用平台或全网数据。
3. 需要构造查询条件时，读取 `.claude/skills/public-opinion-analysis/references/query-contract.md` 并按其规范输出；当前版本不执行外部查询。
4. 建立证据台账：来源类型、发布者、完整 URL、发布时间、抓取时间、查询参数、独立/转载关系与可信度。
5. 合并转载和近重复内容，将事实陈述、归因观点、分析推断和未决不确定性分开。
6. 重要事实尽量由两个独立可信来源交叉验证；做不到时标注“单一来源”或“未证实”。
7. 聚类议题、叙事和立场。只有数据集和采样方法支持时才报告占比、趋势、热度和覆盖范围。
8. 读取 `.claude/skills/public-opinion-analysis/references/risk-rubric.md` 完成风险分级，并给出升级和降级信号。
9. 按 `.claude/skills/public-opinion-analysis/references/report-contract.md` 交付；每条具体帖子或报道都链接原文。

## 产物

- 默认直接在对话中回答。
- 用户明确要求文件、HTML、表格或图表时，读取 `.claude/skills/public-opinion-analysis/references/report-rendering.md`，把唯一最终交付物写入 `outputs/`。
- 最终报告校验优先使用 Glob、Read 和 Grep；也可使用平台自动判定为低风险的隔离沙箱只读 Bash，不要为了绕过策略改写命令。
- 优先使用平台原生工作区、产物发布和记忆能力，不迁移旧版对象存储上传、固定卷路径或自建用户记忆写入。
- 只把稳定且有长期价值的偏好提交给 consent-gated memory 工具；不保存秘密、个人敏感信息或一次性任务细节。

## Reference 路径

调用 Read 时使用上述 `.claude/skills/public-opinion-analysis/references/...` 工作区相对路径，或直接使用 Glob 返回的相对路径。不要把路径展开为 `/root/.claude/skills/...`、`~/.claude/skills/...` 或其他 HOME 绝对路径。

## 当前版本边界

`0.3.14` 未声明知识库、外部 MCP、联网搜索、Task 或 Sub Agent。只使用当前工作区材料与内置文件、Shell 工具，并明确“未接入专用舆情数据源”。

## 禁止事项

不执行发帖、删帖、封禁、账号查询、开盒或对外联络。不虚构情感比例、传播量、趋势、行政区划编码或“全网覆盖”。
