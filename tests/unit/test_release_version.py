from pathlib import Path

import pytest

from harness.versioning import audit_platform_version


def test_every_shipped_surface_and_changelog_use_one_version() -> None:
    audit = audit_platform_version(Path.cwd(), expected="0.2.0")

    assert audit.platform_version == "0.2.0"
    assert set(audit.sources.values()) == {"0.2.0"}
    assert audit.changelog_entry == "## [0.2.0]"
    assert audit.release_state == "2026-08-09"


def test_requested_release_version_must_match_repository() -> None:
    with pytest.raises(ValueError, match="does not match"):
        audit_platform_version(Path.cwd(), expected="0.3.0")


def test_formal_release_requires_a_dated_changelog(tmp_path: Path) -> None:
    changelog = (Path.cwd() / "CHANGELOG.md").read_text(encoding="utf-8")
    candidate = changelog.replace(
        "## [0.2.0] - 2026-08-09", "## [0.2.0] - Unreleased", 1
    )
    repository = tmp_path / "repository"
    repository.mkdir()
    for relative in (
        "pyproject.toml",
        "web/harness-console/package.json",
        "deploy/helm/agent-harness/Chart.yaml",
        "src/harness/__init__.py",
    ):
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((Path.cwd() / relative).read_bytes())
    (repository / "CHANGELOG.md").write_text(candidate, encoding="utf-8")

    with pytest.raises(ValueError, match="must have an ISO date"):
        audit_platform_version(repository, expected="0.2.0", require_released=True)
