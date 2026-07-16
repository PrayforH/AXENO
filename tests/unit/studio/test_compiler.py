from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

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
        }.issubset(names)
        manifest = bundle.read("agent.yaml").decode()
    assert "route: new-api-default" in manifest
    assert "mode: isolated" in manifest


def test_tavily_is_a_controlled_external_mcp_capability_not_general_network() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())
    current = draft()
    enabled = current.model_copy(
        update={
            "spec": current.spec.model_copy(
                update={"mcp_servers": ("tavily-readonly",)}
            )
        }
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


def test_unknown_model_tool_and_mcp_fail_closed_before_packaging() -> None:
    compiler = AgentDraftCompiler(default_capability_catalog())
    current = draft()
    invalid = current.model_copy(
        update={
            "spec": current.spec.model_copy(
                update={
                    "model": current.spec.model.model_copy(
                        update={"route_id": "unreviewed-route"}
                    ),
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
