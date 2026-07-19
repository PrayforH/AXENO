# Archestra 布局对比与 Agent Studio 适配

## 1. 对比依据

本次对比以 Archestra `main` 分支当前实现为准：

- `platform/frontend/src/app/_parts/sidebar.tsx`：AI / Studio 模式切换、折叠侧栏与分组导航；
- `platform/frontend/src/app/_parts/chat-sidebar-section.tsx`：最近对话、固定项和对象级操作；
- `platform/frontend/src/components/page-layout.tsx`：页头、描述、动作和页签的稳定骨架；
- `platform/frontend/src/app/agents/page.client.tsx`：Agent 目录与创建、筛选、管理动作。

参考：

- <https://github.com/archestra-ai/archestra>
- <https://archestra.ai/docs/platform-chat>
- <https://archestra.ai/docs/platform-agents>

## 2. 布局差异

| 领域 | Archestra | 调整前 Agent Studio | 适配结论 |
| --- | --- | --- | --- |
| 全局侧栏 | AI / Studio 两种模式，共用品牌、折叠和用户区 | 任务与 Studio 各自组织导航，视觉相似但语义不一致 | 增加“任务 / Studio”模式切换 |
| 任务上下文 | 新建对话与最近对话在同一模式内 | 新建任务藏在小图标中，工作区入口和任务列表竞争注意力 | 新建任务改为主操作，最近任务单独分组 |
| Studio 上下文 | Studio 模式内再按 Agent、MCP、LLM 等领域分组 | 智能体目录与全局工作区入口混在一起 | Studio 模式下只显示智能体、数据，再进入智能体目录 |
| 页面骨架 | 整高侧栏，右侧页头和内容独立滚动 | 任务页顶部栏横跨侧栏，品牌和智能体选择器上下叠放 | 侧栏贯穿整高，右侧顶部栏只承载当前智能体与运行详情 |
| 发布状态 | 复杂动作渐进披露 | 五段发布轨迹持续占据横向空间 | 默认只显示当前状态，完整发布链按需展开 |

## 3. 本轮采用

1. 共享侧栏增加“任务 / Studio”分段切换，路由决定当前模式。
2. 任务侧栏改为品牌、模式、新建任务、最近任务、用户五层结构。
3. Studio 侧栏改为品牌、模式、管理导航、智能体目录、用户五层结构。
4. 折叠状态继续提供任务、智能体、数据三个直接入口，避免模式切换增加点击成本。
5. 任务页改为整高侧栏；智能体选择和运行详情只占右侧顶部栏。
6. 发布生命周期改成当前状态摘要和可展开的完整发布链。

## 4. 明确不照搬

- 不引入 Archestra 的大型 MCP、LLM、知识库和 ChatOps 菜单；当前产品边界仍由 Agent Studio
  Manifest、发布和运行模型决定。
- 不把 Agent 编辑退化成弹窗或单一表格；当前版本、能力、沙箱、评测和发布信息需要可持续
  浏览的工作台。
- 不加入 Auto 工具入口；Agent 仍只能使用发布清单明确声明的能力。
- 不改变任务与 Agent 版本绑定、审批、取消、Artifact 和恢复语义。

## 5. 验收

- 展开侧栏时只出现一组“任务 / Studio”模式切换。
- 任务侧栏的新建任务是明确主操作，最近任务有独立标题和数量。
- Studio 模式保留智能体与数据入口，并继续支持智能体搜索和版本切换。
- 任务侧栏高度等于视口高度，右侧顶部栏从侧栏右边缘开始。
- 完整发布链默认收起，展开后不越出视口。
- 浅色和深色均无大块异色孤岛；折叠后侧栏宽度保持 52px。
