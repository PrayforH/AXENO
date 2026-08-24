from pathlib import Path

from harness.agent_package import check_agent_package


def test_public_opinion_reference_agent_passes_production_package_gates() -> None:
    manifest = Path("agents/public-opinion-agent/agent.yaml")

    report = check_agent_package(manifest, environment="production")

    assert report.snapshot.manifest.metadata.name == "public-opinion-agent"
    assert report.snapshot.manifest.metadata.version == "0.3.18"
    assert report.snapshot.manifest.spec.model.model == "deepseek-v4-flash-vision-exp"
    assert report.snapshot.manifest.spec.limits.max_tool_calls == 512
    assert report.snapshot.manifest.spec.limits.timeout_seconds == 7200
    assert "涉非舆情分析智能体" in report.snapshot.system_prompt
    assert "当前版本未接入知识库或公网搜索" in report.snapshot.system_prompt
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
