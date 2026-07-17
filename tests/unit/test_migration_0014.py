from importlib import import_module
from typing import Any

import pytest


class _MixedLegacyInspector:
    def has_table(self, table: str) -> bool:
        return table == "runs"

    def get_columns(self, table: str) -> list[dict[str, str]]:
        assert table == "runs"
        return [{"name": "updated_at"}]

    def get_indexes(self, table: str) -> list[dict[str, str]]:
        assert table == "runs"
        return [{"name": "ix_runs_updated_at"}]


def test_0014_upgrade_tolerates_preexisting_run_reliability_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = import_module(
        "migrations.versions.0014_platform_reliability_operations"
    )
    created_tables: list[str] = []
    created_indexes: list[str] = []
    added_columns: list[str] = []

    def inspect(_bind: Any) -> _MixedLegacyInspector:
        return _MixedLegacyInspector()

    def create_table(name: str, *_columns: Any) -> None:
        created_tables.append(name)

    def create_index(name: str, *_args: Any, **_kwargs: Any) -> None:
        created_indexes.append(name)

    def add_column(table: str, _column: Any) -> None:
        added_columns.append(table)

    monkeypatch.setattr(migration.sa, "inspect", inspect)
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration.op, "create_table", create_table)
    monkeypatch.setattr(migration.op, "create_index", create_index)
    monkeypatch.setattr(migration.op, "add_column", add_column)

    migration.upgrade()

    assert added_columns == []
    assert created_tables == [
        "reliability_incidents",
        "reaper_actions",
        "capacity_snapshots",
    ]
    assert created_indexes == [
        "ix_reliability_incidents_status",
        "ix_reliability_incidents_recovery",
        "ix_reaper_actions_tenant_occurred",
        "ix_capacity_snapshots_captured",
    ]
