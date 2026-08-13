"""Reviewed capabilities that Agent drafts may reference by logical ID."""

from harness.studio.models import (
    AgentTemplate,
    BuiltinToolCapability,
    CapabilityCatalog,
    CapabilityRisk,
    ExecutionProfileMetadata,
    McpCapability,
    ModelRouteCapability,
    NetworkAccess,
    PolicyCapability,
    TemplateCapability,
)


def default_capability_catalog() -> CapabilityCatalog:
    """Return the safe built-in catalog used until persistent catalogs are wired."""

    return CapabilityCatalog(
        modelRoutes=(
            ModelRouteCapability(
                routeId="new-api-default",
                label="DeepSeek V4（兼容路由）",
                provider="deepseek",
                models=("deepseek-v4-pro",),
                capabilities=("streaming", "tool_use"),
                credentialReference="NEW_API_KEY",
                version=2,
                enabled=False,
            ),
            ModelRouteCapability(
                routeId="deepseek-v4-flash",
                label="DeepSeek V4 Flash",
                provider="deepseek",
                models=("deepseek-v4-flash",),
                capabilities=("streaming", "tool_use"),
                credentialReference="NEW_API_KEY",
            ),
            ModelRouteCapability(
                routeId="deepseek-v4-pro",
                label="DeepSeek V4 Pro",
                provider="deepseek",
                models=("deepseek-v4-pro",),
                capabilities=("streaming", "tool_use"),
                credentialReference="NEW_API_KEY",
            ),
            ModelRouteCapability(
                routeId="minimax-m3",
                label="MiniMax M3",
                provider="minimax",
                models=("MiniMax-M3",),
                capabilities=("streaming", "tool_use", "vision"),
                modelType="vision",
                credentialReference="MINIMAX_M3_API_KEY",
            ),
            ModelRouteCapability(
                routeId="glm-5-2",
                label="GLM-5.2",
                provider="glm",
                models=("shdata-glm",),
                capabilities=("streaming", "tool_use"),
                credentialReference="GLM_5_2_API_KEY",
            ),
            ModelRouteCapability(
                routeId="anthropic-official",
                label="Anthropic official",
                provider="anthropic",
                models=("claude-sonnet-4-6",),
                capabilities=("streaming", "tool_use", "tool_search"),
                credentialReference="ANTHROPIC_API_KEY",
            ),
        ),
        builtinTools=(
            BuiltinToolCapability(
                name="Read",
                label="读取文件",
                description="读取隔离工作区中的文件。",
                risk=CapabilityRisk.LOW,
                executionLocation="sandbox",
                approvalBehavior="自动允许",
            ),
            BuiltinToolCapability(
                name="Glob",
                label="查找文件",
                description="按文件名模式查找隔离工作区内容。",
                risk=CapabilityRisk.LOW,
                executionLocation="sandbox",
                approvalBehavior="自动允许",
            ),
            BuiltinToolCapability(
                name="Grep",
                label="搜索文件内容",
                description="在隔离工作区内检索文本。",
                risk=CapabilityRisk.LOW,
                executionLocation="sandbox",
                approvalBehavior="自动允许",
            ),
            BuiltinToolCapability(
                name="Write",
                label="创建文件",
                description="在隔离工作区中生成文件和交付物。",
                risk=CapabilityRisk.MEDIUM,
                executionLocation="sandbox",
                approvalBehavior="工作区内自动允许，越界写入拒绝",
            ),
            BuiltinToolCapability(
                name="Edit",
                label="编辑文件",
                description="修改隔离工作区中已有文件。",
                risk=CapabilityRisk.MEDIUM,
                executionLocation="sandbox",
                approvalBehavior="工作区内自动允许，越界写入拒绝",
            ),
            BuiltinToolCapability(
                name="Bash",
                label="运行命令",
                description="在隔离工作区中运行受策略约束的命令；安全只读命令自动放行。",
                risk=CapabilityRisk.HIGH,
                executionLocation="sandbox",
                approvalBehavior="安全命令自动允许，危险、越界或无法证明安全的命令拒绝或审批",
            ),
            BuiltinToolCapability(
                name="Task",
                label="委派子 Agent",
                description="把边界清晰的子任务委派给固定版本 Agent。",
                risk=CapabilityRisk.MEDIUM,
                executionLocation="runtime",
                approvalBehavior="受主/子 Agent 双重权限上限约束",
            ),
        ),
        mcpServers=(
            McpCapability(
                reference="tavily-readonly",
                serverName="tavily",
                label="公网搜索（Tavily）",
                description="检索和抽取公开网页，不提供网页写入能力。",
                endpointUrl="https://mcp.tavily.com/mcp/",
                tools=(
                    "mcp__tavily__tavily_search",
                    "mcp__tavily__tavily_extract",
                ),
                risk=CapabilityRisk.MEDIUM,
                networkAccess=NetworkAccess.EXTERNAL,
                sendsUserData=True,
                readOnly=True,
                executionLocation="external-mcp",
                credentialReference="TAVILY_API_KEY",
                authMode="query",
                authName="tavilyApiKey",
                authKey="api_key",
            ),
        ),
        policies=(
            PolicyCapability(
                policyId="production-read-only",
                label="生产只读",
                description="文件读取和审核过的只读 MCP；其他能力隐式拒绝。",
                risk=CapabilityRisk.LOW,
            ),
            PolicyCapability(
                policyId="production-standard",
                label="生产标准",
                description="允许受控文件写入，命令和高风险动作进入审批。",
                risk=CapabilityRisk.MEDIUM,
            ),
            PolicyCapability(
                policyId="production-orchestrator",
                label="生产编排",
                description="允许固定版本子 Agent 委派，并继承各自权限上限。",
                risk=CapabilityRisk.MEDIUM,
            ),
        ),
        executionProfiles=(
            ExecutionProfileMetadata.model_validate(
                {
                    "profileId": "local-development",
                    "label": "本地开发 Preview",
                    "description": (
                        "仅用于显式启用 unsafe local sandbox 的单机开发与 Preview；"
                        "不提供进程、文件系统或网络强隔离，禁止用于生产发布。"
                    ),
                    "sandboxProvider": "local",
                    "networkAccess": (
                        NetworkAccess.NONE,
                        NetworkAccess.INTERNAL,
                        NetworkAccess.EXTERNAL,
                    ),
                    "risk": CapabilityRisk.HIGH,
                    "cpuMillis": 1000,
                    "memoryMiB": 2048,
                    "diskMiB": 10240,
                    "ttlSeconds": 3600,
                    "networkPolicyId": "unsafe-local-preview",
                    "allowedMcpReferences": ("tavily-readonly",),
                    "providerConfigReference": "local-unsafe-opt-in",
                    "productionAllowed": False,
                }
            ),
            ExecutionProfileMetadata.model_validate(
                {
                    "profileId": "isolated-default",
                    "label": "生产隔离执行",
                    "description": "在平台托管的隔离 Sandbox 中执行文件、命令和工具。",
                    "sandboxProvider": "daytona",
                    "networkAccess": (
                        NetworkAccess.NONE,
                        NetworkAccess.INTERNAL,
                        NetworkAccess.EXTERNAL,
                    ),
                    "risk": CapabilityRisk.MEDIUM,
                    "cpuMillis": 2000,
                    "memoryMiB": 4096,
                    "diskMiB": 20480,
                    "ttlSeconds": 3600,
                    "networkPolicyId": "registered-mcp-only",
                    "allowedMcpReferences": ("tavily-readonly",),
                    "providerConfigReference": "daytona-managed",
                    "productionAllowed": True,
                }
            ),
            ExecutionProfileMetadata.model_validate(
                {
                    "profileId": "e2b-public-egress",
                    "label": "E2B 公网隔离执行",
                    "description": ("在 E2B 隔离微虚拟机中执行，允许访问审核过的公网模型与 MCP。"),
                    "sandboxProvider": "e2b",
                    "networkAccess": (
                        NetworkAccess.NONE,
                        NetworkAccess.EXTERNAL,
                    ),
                    "risk": CapabilityRisk.MEDIUM,
                    "cpuMillis": 2000,
                    "memoryMiB": 4096,
                    "diskMiB": 20480,
                    "ttlSeconds": 3600,
                    "networkPolicyId": "registered-public-mcp",
                    "allowedMcpReferences": ("tavily-readonly",),
                    "providerConfigReference": "e2b-managed",
                    "productionAllowed": True,
                }
            ),
            ExecutionProfileMetadata.model_validate(
                {
                    "profileId": "gvisor-production",
                    "label": "私有化 gVisor",
                    "description": "每个 Run 在 Kubernetes gVisor Pod 中强隔离执行。",
                    "sandboxProvider": "gvisor",
                    "networkAccess": (
                        NetworkAccess.NONE,
                        NetworkAccess.INTERNAL,
                        NetworkAccess.EXTERNAL,
                    ),
                    "risk": CapabilityRisk.MEDIUM,
                    "cpuMillis": 2000,
                    "memoryMiB": 4096,
                    "diskMiB": 20480,
                    "ttlSeconds": 3600,
                    "networkPolicyId": "registered-mcp-only",
                    "allowedMcpReferences": ("tavily-readonly",),
                    "providerConfigReference": "kubernetes-gvisor-managed",
                    "productionAllowed": True,
                }
            ),
        ),
        templates=(
            TemplateCapability(
                template=AgentTemplate.ANALYST,
                label="分析型",
                description="读取、检索、归纳和报告，默认最小只读权限。",
            ),
            TemplateCapability(
                template=AgentTemplate.OPERATOR,
                label="执行型",
                description="在隔离工作区中生成或修改文件，高风险操作需审批。",
            ),
            TemplateCapability(
                template=AgentTemplate.ORCHESTRATOR,
                label="编排型",
                description="将可独立验收的任务委派给固定版本子 Agent。",
            ),
        ),
    )
