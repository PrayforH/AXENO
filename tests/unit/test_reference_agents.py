from pathlib import Path

from harness.agent_package import check_agent_package


def test_public_opinion_reference_agent_passes_production_package_gates() -> None:
    manifest = Path("agents/public-opinion-agent/agent.yaml")

    report = check_agent_package(manifest, environment="production")

    assert report.snapshot.manifest.metadata.name == "public-opinion-agent"
    assert report.snapshot.manifest.spec.permissions.policy == "production-orchestrator"
    assert [skill.name for skill in report.snapshot.skill_snapshots] == [
        "public-opinion-analysis"
    ]
    assert {tag for case in report.eval_suite.cases for tag in case.tags} >= {
        "happy",
        "ambiguous",
        "safety",
    }
