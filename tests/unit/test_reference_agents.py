from pathlib import Path

from harness.agent_package import check_agent_package


def test_public_opinion_reference_agent_passes_production_package_gates() -> None:
    manifest = Path("agents/public-opinion-agent/agent.yaml")

    report = check_agent_package(manifest, environment="production")

    assert report.snapshot.manifest.metadata.name == "public-opinion-agent"
    assert report.snapshot.manifest.metadata.version == "0.3.5"
    assert report.snapshot.manifest.spec.model.model == "deepseek-v4-pro"
    assert (
        ".claude/skills/public-opinion-analysis/references/query-contract.md"
        in report.snapshot.system_prompt
    )
    assert "不得改写为 `/root/.claude/skills/...`" in report.snapshot.system_prompt
    assert "隔离沙箱内的低风险只读 Bash" in report.snapshot.system_prompt
    assert report.snapshot.manifest.spec.permissions.policy == "production-orchestrator"
    assert "Edit" in {
        tool.builtin for tool in report.snapshot.manifest.spec.tools
    }
    assert "Bash" in {
        tool.builtin for tool in report.snapshot.manifest.spec.tools
    }
    assert {
        subagent.alias for subagent in report.snapshot.manifest.spec.subagents
    } == {"fact-researcher", "audience-analyst", "industry-analyst"}
    assert [skill.name for skill in report.snapshot.skill_snapshots] == [
        "public-opinion-analysis"
    ]
    assert {
        Path(file.path).name
        for file in report.snapshot.skill_snapshots[0].files
    } >= {
        "query-contract.md",
        "report-contract.md",
        "report-rendering.md",
        "risk-rubric.md",
    }
    assert {tag for case in report.eval_suite.cases for tag in case.tags} >= {
        "happy",
        "ambiguous",
        "safety",
        "query",
        "artifact",
    }
    artifact_case = next(
        case for case in report.eval_suite.cases if case.id == "html-report-artifact"
    )
    assert "Bash" not in artifact_case.expect.forbidden_tools
