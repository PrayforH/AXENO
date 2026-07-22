"""Compile Studio drafts into the existing reproducible Agent bundle format."""

from __future__ import annotations

import json
import pprint
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from harness.agent_package import (
    AgentPackageCheckError,
    AgentPackageReport,
    check_agent_package,
    pack_agent_package,
)
from harness.core.manifest import (
    TOOL_DIRECTORY_FILENAME,
    AgentManifest,
    ToolDirectoryEntry,
    ToolDirectorySnapshot,
)
from harness.evals.suite import EvalSuite
from harness.studio.bundle_format import (
    STUDIO_BUNDLE_METADATA_FILENAME,
    StudioBundleMetadata,
)
from harness.studio.models import (
    AgentDraft,
    CapabilityCatalog,
    CapabilityRisk,
    DraftValidationResult,
    EffectiveAgentContract,
    NetworkAccess,
    ValidationIssue,
    ValidationSeverity,
)


class DraftCompilationError(ValueError):
    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        super().__init__("Agent draft is not ready: " + "; ".join(i.message for i in issues))


@dataclass(frozen=True)
class CompiledAgentDraft:
    bundle: bytes
    filename: str
    report: AgentPackageReport
    manifest_yaml: str


_FUTURE_IMPORT = re.compile(r"(?m)^from __future__\s+import\s+[^\n]+\n?")


def _python_tool_source(code: str, metadata: str) -> str:
    """Insert generated metadata without invalidating module future imports."""
    generated = (
        "# Generated metadata is part of the editable Bundle tool contract.\n"
        f"TOOL_SPEC = {metadata}\n\n"
    )
    matches = list(_FUTURE_IMPORT.finditer(code))
    if not matches:
        return f"{generated}{code.strip()}\n"
    insertion = matches[-1].end()
    return f"{code[:insertion]}\n{generated}{code[insertion:].strip()}\n"


class AgentDraftCompiler:
    def __init__(
        self,
        catalog: CapabilityCatalog,
        *,
        catalog_revision: int = 1,
    ) -> None:
        self._catalog = catalog
        self._catalog_revision = catalog_revision

    def render_manifest(self, draft: AgentDraft) -> str:
        spec = draft.spec
        required_capabilities = list(spec.model.required_capabilities)
        if spec.tool_exposure_mode == "on_demand" and "tool_search" not in required_capabilities:
            required_capabilities.append("tool_search")
        tools: list[dict[str, str]] = [{"builtin": name} for name in spec.builtin_tools]
        tools.extend(
            {"python": f"bundle:tools/{tool.name}.py"}
            for tool in spec.python_tools
        )
        tools.extend({"mcp": reference} for reference in spec.mcp_servers)
        manifest = AgentManifest.model_validate(
            {
                "apiVersion": "harness/v1alpha1",
                "kind": "Agent",
                "metadata": {
                    "name": spec.name,
                    "version": spec.version,
                    "labels": {
                        "domain": spec.domain,
                        "template": spec.template.value,
                        "display-name": spec.display_name,
                        "description": spec.description,
                        "evaluation-enabled": str(spec.evaluation_enabled).lower(),
                    },
                },
                "spec": {
                    "runtime": "claude-agent-sdk",
                    "model": {
                        "route": spec.model.route_id,
                        "model": spec.model.model,
                        "fallbackRoute": spec.model.fallback_route_id,
                        "fallbackModel": spec.model.fallback_model,
                        "requiredCapabilities": required_capabilities,
                    },
                    "prompt": {"system": "prompts/system.md"},
                    "skills": [f"skills/{skill.name}" for skill in spec.skills],
                    "tools": tools,
                    "toolExposureMode": spec.tool_exposure_mode,
                    "knowledgeReferences": list(spec.knowledge_references),
                    "subagents": [
                        {
                            "ref": subagent.ref,
                            "alias": subagent.alias,
                            "description": subagent.responsibility,
                            "background": subagent.background,
                        }
                        for subagent in spec.subagents
                    ],
                    "hooks": [],
                    "permissions": {"policy": spec.permission_policy},
                    "workspace": {
                        "mode": "isolated",
                        "restoreSession": spec.workspace.restore_session,
                        "archiveOnComplete": spec.workspace.archive_on_complete,
                    },
                    "limits": {
                        "maxTurns": spec.limits.max_turns,
                        "timeoutSeconds": spec.limits.timeout_seconds,
                        "maxBudgetUsd": spec.limits.max_budget_usd,
                        "maxModelTokens": spec.limits.max_model_tokens,
                        "maxSubagents": spec.limits.max_subagents,
                        "maxSubagentTasks": spec.limits.max_subagent_tasks,
                        "maxConcurrentSubagents": (spec.limits.max_concurrent_subagents),
                        "maxSubagentDepth": 1,
                        "maxSubagentUsageUnits": (spec.limits.max_subagent_usage_units),
                    },
                },
            }
        )
        return yaml.safe_dump(
            manifest.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=False,
            allow_unicode=True,
        )

    def validate(self, draft: AgentDraft) -> DraftValidationResult:
        manifest_yaml = self.render_manifest(draft)
        issues = list(self._catalog_issues(draft))
        report: AgentPackageReport | None = None
        if not any(issue.severity is ValidationSeverity.ERROR for issue in issues):
            with TemporaryDirectory(prefix="harness-agent-studio-check-") as directory:
                manifest = self._materialize(draft, Path(directory), manifest_yaml)
                try:
                    report = check_agent_package(manifest, environment="production")
                except AgentPackageCheckError as error:
                    for message in error.issues:
                        prefix = "evaluation suite is missing "
                        suffix = " coverage"
                        if message.startswith(prefix) and message.endswith(suffix):
                            tag = message[len(prefix) : -len(suffix)]
                            issues.append(
                                ValidationIssue(
                                    code=f"evaluation_coverage_{tag}_missing",
                                    message=message,
                                    severity=ValidationSeverity.ERROR,
                                    path="evaluationCases",
                                )
                            )
                        else:
                            issues.append(
                                ValidationIssue(
                                    code="package_check_failed",
                                    message=message,
                                    severity=ValidationSeverity.ERROR,
                                )
                            )
        issues.extend(self._deployment_warnings(draft))
        return DraftValidationResult(
            ready=not any(issue.severity is ValidationSeverity.ERROR for issue in issues),
            issues=tuple(issues),
            contract=self.effective_contract(draft),
            manifestYaml=manifest_yaml,
            contentHash=(report.snapshot.content_hash if report is not None else None),
            packageHash=(report.package_hash if report is not None else None),
        )

    def compile(self, draft: AgentDraft) -> CompiledAgentDraft:
        validation = self.validate(draft)
        if not validation.ready:
            raise DraftCompilationError(
                tuple(
                    issue
                    for issue in validation.issues
                    if issue.severity is ValidationSeverity.ERROR
                )
            )
        with TemporaryDirectory(prefix="harness-agent-studio-pack-") as directory:
            root = Path(directory)
            manifest = self._materialize(draft, root, validation.manifest_yaml)
            archive, report = pack_agent_package(manifest, output_directory=root / "dist")
            return CompiledAgentDraft(
                bundle=archive.read_bytes(),
                filename=archive.name,
                report=report,
                manifest_yaml=validation.manifest_yaml,
            )

    def effective_contract(self, draft: AgentDraft) -> EffectiveAgentContract:
        spec = draft.spec
        mcp_by_reference = {item.reference: item for item in self._catalog.mcp_servers}
        selected_mcp = [
            item
            for reference in spec.mcp_servers
            if (item := mcp_by_reference.get(reference)) is not None
        ]
        if any(item.network_access is NetworkAccess.EXTERNAL for item in selected_mcp):
            network = NetworkAccess.EXTERNAL
            network_summary = "仅通过审核过的外部 MCP 受控联网"
        elif any(item.network_access is NetworkAccess.INTERNAL for item in selected_mcp):
            network = NetworkAccess.INTERNAL
            network_summary = "仅访问注册的内部 MCP 服务"
        else:
            network = NetworkAccess.NONE
            network_summary = "未启用外部网络能力"

        if "Bash" in spec.builtin_tools or spec.python_tools:
            risk = CapabilityRisk.HIGH
            approval = (
                "自定义算子在隔离 Sandbox 执行；高风险系统动作仍由策略拦截"
                if spec.python_tools
                else "工作区文件写入自动允许；Bash 默认进入人工审批"
            )
        elif any(tool in spec.builtin_tools for tool in ("Write", "Edit", "Task")):
            risk = CapabilityRisk.MEDIUM
            approval = "工作区文件写入自动允许；委派受权限上限约束"
        elif network is not NetworkAccess.NONE:
            risk = CapabilityRisk.MEDIUM
            approval = "只读 MCP 自动允许，未声明能力隐式拒绝"
        else:
            risk = CapabilityRisk.LOW
            approval = "只读能力自动允许，未声明能力隐式拒绝"

        return EffectiveAgentContract(
            model=spec.model.model,
            modelRoute=spec.model.route_id,
            skills=len(spec.skills),
            builtinTools=spec.builtin_tools,
            mcpServers=spec.mcp_servers,
            toolExposureMode=spec.tool_exposure_mode,
            toolDirectoryEntries=len(self.tool_directory(draft).entries),
            knowledgeReferences=spec.knowledge_references,
            networkAccess=network,
            networkSummary=network_summary,
            permissionPolicy=spec.permission_policy,
            approvalSummary=approval,
            sandbox="isolated",
            risk=risk,
        )

    def _catalog_issues(self, draft: AgentDraft) -> tuple[ValidationIssue, ...]:
        spec = draft.spec
        issues: list[ValidationIssue] = []
        routes = {route.route_id: route for route in self._catalog.model_routes}
        route = routes.get(spec.model.route_id)
        if route is None:
            issues.append(
                ValidationIssue(
                    code="model_route_unknown",
                    message=f"模型路由未注册：{spec.model.route_id}",
                    severity=ValidationSeverity.ERROR,
                    path="model.routeId",
                )
            )
        else:
            if not route.enabled:
                issues.append(
                    ValidationIssue(
                        code="model_route_disabled",
                        message=f"模型路由已禁用：{spec.model.route_id}",
                        severity=ValidationSeverity.ERROR,
                        path="model.routeId",
                    )
                )
            if route.models and spec.model.model not in route.models:
                issues.append(
                    ValidationIssue(
                        code="model_not_available",
                        message=(f"模型 {spec.model.model} 不属于路由 {spec.model.route_id}"),
                        severity=ValidationSeverity.ERROR,
                        path="model.model",
                    )
                )
            missing = set(spec.model.required_capabilities) - set(route.capabilities)
            if missing:
                issues.append(
                    ValidationIssue(
                        code="model_capability_missing",
                        message=f"模型路由缺少能力：{', '.join(sorted(missing))}",
                        severity=ValidationSeverity.ERROR,
                        path="model.requiredCapabilities",
                    )
                )
            if spec.tool_exposure_mode == "on_demand" and "tool_search" not in route.capabilities:
                issues.append(
                    ValidationIssue(
                        code="tool_search_capability_missing",
                        message=(f"模型路由不支持按需工具加载：{spec.model.route_id}"),
                        severity=ValidationSeverity.ERROR,
                        path="toolExposureMode",
                    )
                )

        builtins = {tool.name for tool in self._catalog.builtin_tools}
        for name in spec.builtin_tools:
            if name not in builtins:
                issues.append(
                    ValidationIssue(
                        code="builtin_tool_unknown",
                        message=f"内建工具未注册：{name}",
                        severity=ValidationSeverity.ERROR,
                        path="builtinTools",
                    )
                )
        mcp_servers = {server.reference: server for server in self._catalog.mcp_servers}
        if spec.python_tools and spec.tool_exposure_mode == "on_demand":
            issues.append(
                ValidationIssue(
                    code="python_tool_on_demand_unsupported",
                    message="自定义算子仅支持启动时加载",
                    severity=ValidationSeverity.ERROR,
                    path="pythonTools",
                )
            )
        if spec.tool_exposure_mode == "on_demand" and not spec.mcp_servers:
            issues.append(
                ValidationIssue(
                    code="tool_search_without_mcp",
                    message="按需工具加载至少需要一个 MCP 工具源",
                    severity=ValidationSeverity.ERROR,
                    path="toolExposureMode",
                )
            )
        for reference in spec.mcp_servers:
            server = mcp_servers.get(reference)
            if server is None:
                issues.append(
                    ValidationIssue(
                        code="mcp_server_unknown",
                        message=f"MCP 能力未注册：{reference}",
                        severity=ValidationSeverity.ERROR,
                        path="mcpServers",
                    )
                )
            elif not server.enabled:
                issues.append(
                    ValidationIssue(
                        code="mcp_server_disabled",
                        message=f"MCP 能力已禁用：{reference}",
                        severity=ValidationSeverity.ERROR,
                        path="mcpServers",
                    )
                )
        policies = {policy.policy_id: policy for policy in self._catalog.policies}
        policy = policies.get(spec.permission_policy)
        if policy is None:
            issues.append(
                ValidationIssue(
                    code="policy_unknown",
                    message=f"权限 Profile 未注册：{spec.permission_policy}",
                    severity=ValidationSeverity.ERROR,
                    path="permissionPolicy",
                )
            )
        elif not policy.enabled:
            issues.append(
                ValidationIssue(
                    code="policy_disabled",
                    message=f"权限 Profile 已禁用：{spec.permission_policy}",
                    severity=ValidationSeverity.ERROR,
                    path="permissionPolicy",
                )
            )
        profiles = {profile.profile_id: profile for profile in self._catalog.execution_profiles}
        profile = profiles.get(spec.execution_profile)
        if profile is None:
            issues.append(
                ValidationIssue(
                    code="execution_profile_unknown",
                    message=f"执行 Profile 未注册：{spec.execution_profile}",
                    severity=ValidationSeverity.ERROR,
                    path="executionProfile",
                )
            )
        elif not profile.enabled:
            issues.append(
                ValidationIssue(
                    code="execution_profile_disabled",
                    message=f"执行 Profile 已禁用：{spec.execution_profile}",
                    severity=ValidationSeverity.ERROR,
                    path="executionProfile",
                )
            )
        elif any(
            server.network_access not in profile.network_access
            for reference in spec.mcp_servers
            if (server := mcp_servers.get(reference)) is not None
        ):
            issues.append(
                ValidationIssue(
                    code="execution_profile_network_incompatible",
                    message="执行 Profile 不允许所选 MCP 的网络访问级别",
                    severity=ValidationSeverity.ERROR,
                    path="executionProfile",
                )
            )
        elif {reference for reference in spec.mcp_servers if reference in mcp_servers}.difference(
            profile.allowed_mcp_references
        ):
            issues.append(
                ValidationIssue(
                    code="execution_profile_egress_incompatible",
                    message="执行 Profile 的 Egress Policy 未关联所选 MCP",
                    severity=ValidationSeverity.ERROR,
                    path="executionProfile",
                )
            )
        return tuple(issues)

    def _deployment_warnings(self, draft: AgentDraft) -> tuple[ValidationIssue, ...]:
        mcp_by_reference = {item.reference: item for item in self._catalog.mcp_servers}
        warnings = [
            ValidationIssue(
                code="mcp_deployment_preflight_required",
                message=(
                    f"发布部署前需从实际 Sandbox 校验 {reference} 的凭据、"
                    "MCP tools/list 和网络可达性"
                ),
                severity=ValidationSeverity.WARNING,
                path="mcpServers",
            )
            for reference in draft.spec.mcp_servers
            if (capability := mcp_by_reference.get(reference)) is not None
            and capability.preflight_required
        ]
        return tuple(warnings)

    def tool_directory(self, draft: AgentDraft) -> ToolDirectorySnapshot:
        builtin_by_name = {item.name: item for item in self._catalog.builtin_tools}
        mcp_by_reference = {item.reference: item for item in self._catalog.mcp_servers}
        entries: list[ToolDirectoryEntry] = []
        for name in draft.spec.builtin_tools:
            capability = builtin_by_name.get(name)
            if capability is None:
                continue
            entries.append(
                ToolDirectoryEntry(
                    name=name,
                    source="builtin",
                    logicalReference=name,
                    description=capability.description,
                    risk=capability.risk.value,
                    resultTrust="safe",
                )
            )
        for reference in draft.spec.mcp_servers:
            capability = mcp_by_reference.get(reference)
            if capability is None:
                continue
            result_trust = (
                "untrusted"
                if capability.network_access is NetworkAccess.EXTERNAL or capability.sends_user_data
                else "sensitive"
            )
            for name in capability.tools:
                entries.append(
                    ToolDirectoryEntry(
                        name=name,
                        source="mcp",
                        logicalReference=reference,
                        description=(
                            f"{capability.description} Reviewed tool: {name.rsplit('__', 1)[-1]}."
                        ),
                        risk=capability.risk.value,
                        resultTrust=result_trust,
                    )
                )
        for tool in draft.spec.python_tools:
            reference = f"bundle:tools/{tool.name}.py"
            entries.append(
                ToolDirectoryEntry(
                    name=(
                        f"mcp__harness-python-{draft.spec.name}__{tool.name}"
                    ),
                    source="python",
                    logicalReference=reference,
                    description=tool.description,
                    risk="high",
                    resultTrust="safe",
                )
            )
        return ToolDirectorySnapshot.create(
            catalog_revision=self._catalog_revision,
            exposure_mode=draft.spec.tool_exposure_mode,
            entries=entries,
        )

    def _materialize(self, draft: AgentDraft, root: Path, manifest_yaml: str) -> Path:
        spec = draft.spec
        prompt = root / "prompts" / "system.md"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text(spec.system_prompt, encoding="utf-8")

        for skill in spec.skills:
            skill_root = root / "skills" / skill.name
            skill_root.mkdir(parents=True, exist_ok=True)
            frontmatter = yaml.safe_dump(
                {"name": skill.name, "description": skill.description},
                sort_keys=False,
                allow_unicode=True,
            ).strip()
            (skill_root / "SKILL.md").write_text(
                f"---\n{frontmatter}\n---\n\n{skill.instructions.strip()}\n",
                encoding="utf-8",
            )
            for file in skill.files:
                target = skill_root.joinpath(*Path(file.path).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(file.content, encoding="utf-8")

        tools_root = root / "tools"
        for tool in spec.python_tools:
            tools_root.mkdir(parents=True, exist_ok=True)
            metadata = pprint.pformat(
                {
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "name": tool.name,
                },
                sort_dicts=True,
                width=100,
            )
            source = _python_tool_source(tool.code, metadata)
            (tools_root / f"{tool.name}.py").write_text(source, encoding="utf-8")

        eval_path = root / "evals" / "suite.yaml"
        eval_path.parent.mkdir(parents=True, exist_ok=True)
        suite = EvalSuite(
            apiVersion="harness/v1alpha1",
            kind="EvalSuite",
            agent=spec.name,
            cases=spec.evaluation_cases,
        )
        eval_path.write_text(
            yaml.safe_dump(
                suite.model_dump(mode="json", by_alias=True, exclude_none=True),
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        (root / "README.md").write_text(
            f"# {spec.display_name}\n\n{spec.description}\n",
            encoding="utf-8",
        )
        (root / STUDIO_BUNDLE_METADATA_FILENAME).write_text(
            json.dumps(
                StudioBundleMetadata(
                    apiVersion="harness.studio/v1",
                    kind="AgentDraftMetadata",
                    description=spec.description,
                    executionProfile=spec.execution_profile,
                ).model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (root / TOOL_DIRECTORY_FILENAME).write_text(
            json.dumps(
                self.tool_directory(draft).model_dump(
                    mode="json",
                    by_alias=True,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest = root / "agent.yaml"
        manifest.write_text(manifest_yaml, encoding="utf-8")
        return manifest
