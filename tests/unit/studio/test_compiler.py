import json
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import yaml

from harness.core.manifest import ToolDirectorySnapshot
from harness.studio.catalog import default_capability_catalog
from harness.studio.compiler import AgentDraftCompiler
from harness.studio.factory import create_draft_spec
from harness.studio.models import (
    AgentDraft,
    AgentDraftSpec,
    AgentTemplate,
    CapabilityRisk,
    NetworkAccess,
    ValidationSeverity,
)

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def draft(template: AgentTemplate = AgentTemplate.ANALYST) -> AgentDraft:
    return AgentDraft(
        draftId="draft_test",
        tenantId="tenant-a",
        revision=1,
        spec=create_draft_spec(
            name="invoice-reviewer",
            domain="accounts-payable",
            display_name="发票审核助手",
            description="核对发票证据并标记需要人工确认的例外。",
            template=template,
        ),
        createdBy="builder-a",
        updatedBy="builder-a",
        createdAt=NOW,
        updatedAt=NOW,
    )


def test_default_draft_compiles_to_existing_reproducible_bundle_contract() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())

    validation = compiler.validate(draft())
    compiled = compiler.compile(draft())

    assert validation.ready is True
    assert validation.content_hash == compiled.report.snapshot.content_hash
    assert validation.package_hash == compiled.report.package_hash
    assert compiled.filename.startswith("invoice-reviewer-0.1.0-")
    with ZipFile(BytesIO(compiled.bundle)) as bundle:
        names = set(bundle.namelist())
        assert {
            "agent.yaml",
            "bundle.json",
            "prompts/system.md",
            "skills/invoice-reviewer-core/SKILL.md",
            "evals/suite.yaml",
            "tool-directory.json",
        }.issubset(names)
        manifest = bundle.read("agent.yaml").decode()
        directory = ToolDirectorySnapshot.model_validate_json(bundle.read("tool-directory.json"))
    assert "route: new-api-default" in manifest
    assert "mode: isolated" in manifest
    assert directory.exposure_mode == "eager"
    assert directory.catalog_revision == 1
    assert {entry.name for entry in directory.entries} == {
        "Read",
        "Glob",
        "Grep",
    }


def test_missing_eval_coverage_has_a_stable_actionable_issue() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())
    current = draft()
    without_ambiguous = current.model_copy(
        update={
            "spec": current.spec.model_copy(
                update={
                    "evaluation_cases": tuple(
                        case
                        for case in current.spec.evaluation_cases
                        if "ambiguous" not in case.tags
                    )
                }
            )
        }
    )

    validation = compiler.validate(without_ambiguous)

    issue = next(
        item
        for item in validation.issues
        if item.code == "evaluation_coverage_ambiguous_missing"
    )
    assert validation.ready is False
    assert issue.path == "evaluationCases"
    assert issue.message == "evaluation suite is missing ambiguous coverage"


def test_disabled_eval_does_not_block_bundle_coverage() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())
    current = draft()
    disabled = current.model_copy(
        update={
            "spec": current.spec.model_copy(
                update={
                    "evaluation_enabled": False,
                    "evaluation_cases": (current.spec.evaluation_cases[0],),
                }
            )
        }
    )

    validation = compiler.validate(disabled)
    compiled = compiler.compile(disabled)

    assert validation.ready is True
    manifest = yaml.safe_load(compiled.manifest_yaml)
    assert manifest["metadata"]["labels"]["evaluation-enabled"] == "false"


def test_knowledge_references_are_pinned_in_manifest_and_effective_contract() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())
    current = draft()
    with_knowledge = current.model_copy(
        update={
            "spec": current.spec.model_copy(update={"knowledge_references": ("company-policy",)})
        }
    )

    validation = compiler.validate(with_knowledge)
    compiled = compiler.compile(with_knowledge)

    assert validation.ready is True
    assert validation.contract.knowledge_references == ("company-policy",)
    assert "knowledgeReferences:" in validation.manifest_yaml
    assert "- company-policy" in validation.manifest_yaml
    with ZipFile(BytesIO(compiled.bundle)) as bundle:
        manifest = bundle.read("agent.yaml").decode()
    assert "knowledgeReferences:" in manifest
    assert "- company-policy" in manifest


def test_tavily_is_a_controlled_external_mcp_capability_not_general_network() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())
    current = draft()
    enabled = current.model_copy(
        update={"spec": current.spec.model_copy(update={"mcp_servers": ("tavily-readonly",)})}
    )

    validation = compiler.validate(enabled)

    assert validation.ready is True
    assert validation.contract.network_access is NetworkAccess.EXTERNAL
    assert validation.contract.network_summary == "仅通过审核过的外部 MCP 受控联网"
    assert validation.contract.risk is CapabilityRisk.MEDIUM
    assert any(
        issue.code == "mcp_deployment_preflight_required"
        and issue.severity is ValidationSeverity.WARNING
        for issue in validation.issues
    )
    assert "mcp: tavily-readonly" in validation.manifest_yaml


def test_on_demand_bundle_pins_reviewed_tool_directory_and_route_capability() -> None:
    compiler = AgentDraftCompiler(
        default_capability_catalog(),
        catalog_revision=9,
    )
    current = draft()
    on_demand = current.model_copy(
        update={
            "spec": current.spec.model_copy(
                update={
                    "model": current.spec.model.model_copy(
                        update={
                            "route_id": "anthropic-official",
                            "model": "claude-sonnet-4-6",
                            "required_capabilities": (
                                "streaming",
                                "tool_use",
                                "tool_search",
                            ),
                        }
                    ),
                    "mcp_servers": ("tavily-readonly",),
                    "tool_exposure_mode": "on_demand",
                }
            )
        }
    )

    validation = compiler.validate(on_demand)
    compiled = compiler.compile(on_demand)

    assert validation.ready is True
    assert validation.contract.tool_exposure_mode == "on_demand"
    assert validation.contract.tool_directory_entries == 5
    assert "toolExposureMode: on_demand" in validation.manifest_yaml
    assert "tool_search" in validation.manifest_yaml
    with ZipFile(BytesIO(compiled.bundle)) as bundle:
        raw = json.loads(bundle.read("tool-directory.json"))
        directory = ToolDirectorySnapshot.model_validate(raw)
    assert directory.catalog_revision == 9
    assert directory.exposure_mode == "on_demand"
    assert directory.content_hash == directory.digest()
    assert {entry.name for entry in directory.entries if entry.source == "mcp"} == {
        "mcp__tavily__tavily_search",
        "mcp__tavily__tavily_extract",
    }
    assert {entry.logical_reference for entry in directory.entries if entry.source == "mcp"} == {
        "tavily-readonly"
    }


def test_on_demand_mode_fails_closed_on_route_without_tool_search() -> None:
    current = draft()
    unsupported = current.model_copy(
        update={"spec": current.spec.model_copy(update={"tool_exposure_mode": "on_demand"})}
    )

    validation = AgentDraftCompiler(default_capability_catalog()).validate(unsupported)

    assert validation.ready is False
    assert "tool_search_capability_missing" in {issue.code for issue in validation.issues}


def test_unknown_model_tool_and_mcp_fail_closed_before_packaging() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())
    current = draft()
    invalid = current.model_copy(
        update={
            "spec": current.spec.model_copy(
                update={
                    "model": current.spec.model.model_copy(update={"route_id": "unreviewed-route"}),
                    "builtin_tools": (*current.spec.builtin_tools, "DangerousTool"),
                    "mcp_servers": ("arbitrary-url",),
                }
            )
        }
    )

    validation = compiler.validate(invalid)

    assert validation.ready is False
    assert {issue.code for issue in validation.issues} == {
        "model_route_unknown",
        "builtin_tool_unknown",
        "mcp_server_unknown",
    }
    assert validation.package_hash is None


def test_sandbox_is_mandatory_and_provider_is_not_authored_by_domain_agent() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())
    operator = draft(AgentTemplate.OPERATOR)

    contract = compiler.effective_contract(operator)

    assert contract.sandbox == "isolated"
    assert contract.risk is CapabilityRisk.HIGH
    assert "Bash 默认进入人工审批" in contract.approval_summary
    assert "sandbox_provider" not in AgentDraftSpec.model_fields


def test_local_development_profile_is_explicitly_preview_only() -> None:
    catalog = default_capability_catalog()
    profile = next(
        item for item in catalog.execution_profiles if item.profile_id == "local-development"
    )
    current = draft()
    local_draft = current.model_copy(
        update={
            "spec": current.spec.model_copy(
                update={
                    "execution_profile": profile.profile_id,
                    "mcp_servers": ("tavily-readonly",),
                }
            )
        }
    )

    validation = AgentDraftCompiler(catalog).validate(local_draft)

    assert validation.ready is True
    assert profile.sandbox_provider == "local"
    assert profile.production_allowed is False
    assert profile.risk is CapabilityRisk.HIGH
    assert NetworkAccess.EXTERNAL in profile.network_access
    assert profile.allowed_mcp_references == ("tavily-readonly",)


def test_orchestrator_compiles_role_descriptions_and_background_mode() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())

    validation = compiler.validate(draft(AgentTemplate.ORCHESTRATOR))

    assert validation.ready is True
    assert "alias: evidence-researcher" in validation.manifest_yaml
    assert "description: 并行收集证据" in validation.manifest_yaml
    assert "background: true" in validation.manifest_yaml
    assert "alias: quality-reviewer" in validation.manifest_yaml


def test_disabled_catalog_resources_fail_closed() -> None:
    catalog = default_capability_catalog()
    disabled = catalog.model_copy(
        update={
            "model_routes": tuple(
                item.model_copy(update={"enabled": False})
                if item.route_id == "new-api-default"
                else item
                for item in catalog.model_routes
            ),
            "policies": tuple(
                item.model_copy(update={"enabled": False})
                if item.policy_id == "production-read-only"
                else item
                for item in catalog.policies
            ),
            "execution_profiles": tuple(
                item.model_copy(update={"enabled": False}) for item in catalog.execution_profiles
            ),
        }
    )

    validation = AgentDraftCompiler(disabled).validate(draft())

    assert validation.ready is False
    assert {issue.code for issue in validation.issues} >= {
        "model_route_disabled",
        "policy_disabled",
        "execution_profile_disabled",
    }


def test_model_and_execution_profile_capabilities_must_be_compatible() -> None:
    catalog = default_capability_catalog()
    incompatible = catalog.model_copy(
        update={
            "model_routes": tuple(
                item.model_copy(update={"capabilities": ("streaming",)})
                if item.route_id == "new-api-default"
                else item
                for item in catalog.model_routes
            ),
            "execution_profiles": tuple(
                item.model_copy(update={"network_access": (NetworkAccess.NONE,)})
                for item in catalog.execution_profiles
            ),
        }
    )
    current = draft()
    with_mcp = current.model_copy(
        update={"spec": current.spec.model_copy(update={"mcp_servers": ("tavily-readonly",)})}
    )

    validation = AgentDraftCompiler(incompatible).validate(with_mcp)

    assert validation.ready is False
    assert {issue.code for issue in validation.issues} >= {
        "model_capability_missing",
        "execution_profile_network_incompatible",
    }


def test_execution_profile_egress_allows_only_registered_mcp_associations() -> None:
    catalog = default_capability_catalog()
    restricted = catalog.model_copy(
        update={
            "execution_profiles": tuple(
                item.model_copy(update={"allowed_mcp_references": ()})
                for item in catalog.execution_profiles
            )
        }
    )
    current = draft()
    with_mcp = current.model_copy(
        update={"spec": current.spec.model_copy(update={"mcp_servers": ("tavily-readonly",)})}
    )

    validation = AgentDraftCompiler(restricted).validate(with_mcp)

    assert "execution_profile_egress_incompatible" in {issue.code for issue in validation.issues}
