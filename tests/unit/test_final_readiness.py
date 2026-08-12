from pathlib import Path

from harness.readiness import audit_repository


def test_repository_has_complete_goal_and_release_evidence() -> None:
    audit = audit_repository(Path.cwd())

    assert audit.platform_version == "0.2.0"
    assert audit.migration_head == "0029"
    assert audit.goal_reports == tuple(f"G{index:02d}" for index in range(20))
    assert audit.external_actions_pinned >= 10
    assert audit.custom_role_decision == "fixed-versioned-roles"
