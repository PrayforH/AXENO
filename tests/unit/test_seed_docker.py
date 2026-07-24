from pathlib import Path

import pytest

from scripts.seed_docker import _numeric_version, studio_spec_from_manifest

ROOT = Path(__file__).parents[2]


def test_numeric_version_orders_seed_versions_without_external_dependencies() -> None:
    assert _numeric_version("0.1.1") > _numeric_version("0.1.0")  # type: ignore[operator]
    assert _numeric_version("release") is None


@pytest.mark.parametrize(
    ("name", "display_name", "template"),
    (
        ("similar-case-analysis-agent", "类案分析", "analyst"),
        ("govdoc-writer-agent", "公文写作", "operator"),
        ("archive-assistant-agent", "档案智能归档", "orchestrator"),
        ("networked-knowledge-research-agent", "联网知识研究", "analyst"),
    ),
)
def test_downloaded_agent_packages_compile_to_studio_specs(
    name: str,
    display_name: str,
    template: str,
) -> None:
    spec = studio_spec_from_manifest(ROOT / "agents" / name / "agent.yaml")

    assert spec["name"] == name
    assert spec["displayName"] == display_name
    assert spec["template"] == template
    assert len(spec["skills"]) >= 1  # type: ignore[arg-type]
    expected_cases = 5 if name == "networked-knowledge-research-agent" else 3
    assert len(spec["evaluationCases"]) == expected_cases  # type: ignore[arg-type]


def test_networked_research_agent_uses_production_profile_and_multiple_mcp() -> None:
    spec = studio_spec_from_manifest(
        ROOT / "agents" / "networked-knowledge-research-agent" / "agent.yaml"
    )

    assert spec["executionProfile"] == "isolated-default"
    assert spec["mcpServers"] == [
        "tavily-readonly",
        "knowledge-search",
    ]
    coverage = {
        tag
        for case in spec["evaluationCases"]  # type: ignore[union-attr]
        for tag in case["tags"]
    }
    assert {"happy", "ambiguous", "safety"} <= coverage


def test_archive_studio_spec_pins_internal_classifier() -> None:
    spec = studio_spec_from_manifest(
        ROOT / "agents" / "archive-assistant-agent" / "agent.yaml"
    )

    assert spec["subagents"] == [
        {
            "alias": "file-classifier",
            "ref": "archive-file-classifier-agent@0.1.1",
            "responsibility": (
                "只读并行分类文件，返回门类、期限、依据、可信度和待复核项。"
            ),
            "background": True,
        }
    ]
