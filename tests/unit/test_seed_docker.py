from pathlib import Path

import pytest

from scripts.seed_docker import studio_spec_from_manifest

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("name", "display_name", "template"),
    (
        ("similar-case-analysis-agent", "类案分析", "analyst"),
        ("govdoc-writer-agent", "公文写作", "operator"),
        ("archive-assistant-agent", "档案智能归档", "orchestrator"),
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
    assert len(spec["evaluationCases"]) == 3  # type: ignore[arg-type]


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
