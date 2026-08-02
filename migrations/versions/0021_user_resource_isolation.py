"""Add user ownership to Agent Studio resources.

Revision ID: 0021
Revises: 0020

The migration deliberately fails when a legacy row cannot be assigned to one
user. Treating an unknown owner as tenant-wide visibility would defeat the
isolation boundary introduced by this revision.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNER_COLUMNS = {
    "agent_versions": "owner_user_id",
    "agent_drafts": "owner_user_id",
    "mcp_credentials": "owner_user_id",
    "preview_deployments": "requested_by",
    "eval_dataset_versions": "created_by",
    "eval_runs": "requested_by",
    "deployment_environments": "owner_user_id",
    "deployment_snapshots": "created_by",
    "deployments": "requested_by",
}


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _payload_owner(payload: object, *keys: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _members_by_tenant(connection: Any) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    inspector = sa.inspect(connection)
    if not inspector.has_table("tenant_memberships"):
        return result
    rows = connection.execute(
        sa.text("SELECT tenant_id, user_id FROM tenant_memberships")
    ).mappings()
    for row in rows:
        result[str(row["tenant_id"])].add(str(row["user_id"]))
    return result


def _draft_owners(connection: Any) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    if not sa.inspect(connection).has_table("agent_drafts"):
        return result
    rows = connection.execute(
        sa.text("SELECT tenant_id, name, payload FROM agent_drafts")
    ).mappings()
    for row in rows:
        owner = _payload_owner(row["payload"], "createdBy", "created_by")
        if owner:
            result[(str(row["tenant_id"]), str(row["name"]))].add(owner)
    return result


def _choose_owner(
    *,
    tenant_id: str,
    direct: str | None,
    candidates: set[str],
    members: dict[str, set[str]],
) -> str | None:
    if direct:
        return direct
    if len(candidates) == 1:
        return next(iter(candidates))
    tenant_members = members.get(tenant_id, set())
    if len(tenant_members) == 1:
        return next(iter(tenant_members))
    return None


def _add_owner_columns() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, column in _OWNER_COLUMNS.items():
        if inspector.has_table(table) and column not in _columns(table):
            op.add_column(table, sa.Column(column, sa.String(128), nullable=True))


def _backfill() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    members = _members_by_tenant(connection)
    draft_owners = _draft_owners(connection)
    unresolved: list[str] = []

    specifications = (
        ("agent_drafts", "draft_id", "owner_user_id", ("createdBy", "created_by")),
        ("preview_deployments", "preview_id", "requested_by", ("requestedBy", "requested_by")),
        ("eval_dataset_versions", "dataset_id", "created_by", ("createdBy", "created_by")),
        ("eval_runs", "eval_run_id", "requested_by", ("requestedBy", "requested_by")),
        ("deployment_snapshots", "snapshot_id", "created_by", ("createdBy", "created_by")),
        ("deployments", "deployment_id", "requested_by", ("requestedBy", "requested_by")),
    )
    for table, identity_column, owner_column, payload_keys in specifications:
        if not inspector.has_table(table):
            continue
        rows = connection.execute(
            sa.text(
                f"SELECT tenant_id, {identity_column} AS resource_id, payload "
                f"FROM {table} WHERE {owner_column} IS NULL"
            )
        ).mappings()
        for row in rows:
            tenant_id = str(row["tenant_id"])
            owner = _choose_owner(
                tenant_id=tenant_id,
                direct=_payload_owner(row["payload"], *payload_keys),
                candidates=set(),
                members=members,
            )
            if owner is None:
                unresolved.append(f"{table}:{tenant_id}:{row['resource_id']}")
                continue
            connection.execute(
                sa.text(
                    f"UPDATE {table} SET {owner_column} = :owner "
                    f"WHERE tenant_id = :tenant AND {identity_column} = :resource"
                ),
                {"owner": owner, "tenant": tenant_id, "resource": row["resource_id"]},
            )

    if inspector.has_table("agent_versions"):
        rows = connection.execute(
            sa.text(
                "SELECT tenant_id, name, version, payload FROM agent_versions "
                "WHERE owner_user_id IS NULL"
            )
        ).mappings()
        for row in rows:
            tenant_id = str(row["tenant_id"])
            owner = _choose_owner(
                tenant_id=tenant_id,
                direct=_payload_owner(row["payload"], "owner_user_id", "ownerUserId"),
                candidates=draft_owners.get((tenant_id, str(row["name"])), set()),
                members=members,
            )
            if owner is None:
                unresolved.append(f"agent_versions:{tenant_id}:{row['name']}@{row['version']}")
                continue
            payload = dict(row["payload"])
            payload["owner_user_id"] = owner
            connection.execute(
                sa.text(
                    "UPDATE agent_versions SET owner_user_id = :owner, payload = :payload "
                    "WHERE tenant_id = :tenant AND name = :name AND version = :version"
                ).bindparams(sa.bindparam("payload", type_=sa.JSON())),
                {
                    "owner": owner,
                    "payload": payload,
                    "tenant": tenant_id,
                    "name": row["name"],
                    "version": row["version"],
                },
            )
        rows = connection.execute(
            sa.text(
                "SELECT tenant_id, name, owner_user_id FROM agent_versions "
                "WHERE owner_user_id IS NOT NULL"
            )
        ).mappings()
        for row in rows:
            draft_owners[(str(row["tenant_id"]), str(row["name"]))].add(str(row["owner_user_id"]))

    if inspector.has_table("deployment_environments"):
        rows = connection.execute(
            sa.text(
                "SELECT tenant_id, agent_name, name, payload "
                "FROM deployment_environments WHERE owner_user_id IS NULL"
            )
        ).mappings()
        for row in rows:
            tenant_id = str(row["tenant_id"])
            owner = _choose_owner(
                tenant_id=tenant_id,
                direct=_payload_owner(row["payload"], "ownerUserId", "owner_user_id"),
                candidates=draft_owners.get((tenant_id, str(row["agent_name"])), set()),
                members=members,
            )
            if owner is None:
                unresolved.append(
                    f"deployment_environments:{tenant_id}:{row['agent_name']}/{row['name']}"
                )
                continue
            payload = dict(row["payload"])
            payload["ownerUserId"] = owner
            connection.execute(
                sa.text(
                    "UPDATE deployment_environments "
                    "SET owner_user_id = :owner, payload = :payload "
                    "WHERE tenant_id = :tenant AND agent_name = :agent AND name = :name"
                ).bindparams(sa.bindparam("payload", type_=sa.JSON())),
                {
                    "owner": owner,
                    "payload": payload,
                    "tenant": tenant_id,
                    "agent": row["agent_name"],
                    "name": row["name"],
                },
            )

    if inspector.has_table("mcp_credentials"):
        rows = connection.execute(
            sa.text(
                "SELECT tenant_id, reference, updated_by FROM mcp_credentials "
                "WHERE owner_user_id IS NULL"
            )
        ).mappings()
        for row in rows:
            tenant_id = str(row["tenant_id"])
            owner = _choose_owner(
                tenant_id=tenant_id,
                direct=str(row["updated_by"] or "").strip() or None,
                candidates=set(),
                members=members,
            )
            if owner is None:
                unresolved.append(f"mcp_credentials:{tenant_id}:{row['reference']}")
                continue
            connection.execute(
                sa.text(
                    "UPDATE mcp_credentials SET owner_user_id = :owner "
                    "WHERE tenant_id = :tenant AND reference = :reference"
                ),
                {
                    "owner": owner,
                    "tenant": tenant_id,
                    "reference": row["reference"],
                },
            )

    _backfill_quality_payloads(
        connection=connection,
        inspector=inspector,
        members=members,
        draft_owners=draft_owners,
        unresolved=unresolved,
    )

    _backfill_session_agent_owners(connection, inspector)

    if unresolved:
        sample = ", ".join(unresolved[:20])
        raise RuntimeError(
            "User-resource isolation migration cannot infer owners; "
            f"resolve these rows before deployment: {sample}"
        )


def _backfill_session_agent_owners(connection: Any, inspector: Any) -> None:
    """Pin the resolved Agent owner for in-flight legacy tasks."""

    if not inspector.has_table("sessions"):
        return
    version_owners: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    if inspector.has_table("agent_versions"):
        rows = connection.execute(
            sa.text(
                "SELECT tenant_id, owner_user_id, name, version "
                "FROM agent_versions WHERE owner_user_id IS NOT NULL"
            )
        ).mappings()
        for row in rows:
            version_owners[(str(row["tenant_id"]), str(row["name"]), str(row["version"]))].add(
                str(row["owner_user_id"])
            )

    trigger_owners: dict[str, str] = {}
    if inspector.has_table("agent_triggers"):
        rows = connection.execute(
            sa.text("SELECT trigger_id, payload FROM agent_triggers")
        ).mappings()
        for row in rows:
            owner = _payload_owner(row["payload"], "createdBy", "created_by")
            if owner:
                trigger_owners[str(row["trigger_id"])] = owner

    rows = connection.execute(
        sa.text("SELECT tenant_id, session_id, user_id, payload FROM sessions")
    ).mappings()
    for row in rows:
        payload = dict(row["payload"])
        if _payload_owner(payload, "agent_owner_user_id", "agentOwnerUserId"):
            continue
        tenant_id = str(row["tenant_id"])
        user_id = str(row["user_id"])
        agent_name = str(payload.get("agent_name") or payload.get("agentName") or "")
        agent_version = str(payload.get("agent_version") or payload.get("agentVersion") or "")
        candidates = version_owners.get((tenant_id, agent_name, agent_version), set())
        owner: str | None = next(iter(candidates)) if len(candidates) == 1 else None
        if user_id.startswith("eval:"):
            owner = user_id.removeprefix("eval:") or owner
        elif user_id.startswith("trigger:"):
            owner = trigger_owners.get(user_id.removeprefix("trigger:"), owner)
        else:
            owner = owner or user_id
        if not owner:
            continue
        payload["agent_owner_user_id"] = owner
        connection.execute(
            sa.text(
                "UPDATE sessions SET payload = :payload "
                "WHERE tenant_id = :tenant AND session_id = :session"
            ).bindparams(sa.bindparam("payload", type_=sa.JSON())),
            {
                "payload": payload,
                "tenant": tenant_id,
                "session": row["session_id"],
            },
        )


def _replace_primary_key(table: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    current = inspector.get_pk_constraint(table)
    current_columns = current.get("constrained_columns") or []
    if current_columns == columns:
        return
    name = current.get("name")
    if name:
        op.drop_constraint(name, table, type_="primary")
    op.create_primary_key(f"pk_{table}", table, columns)


def _backfill_quality_payloads(
    *,
    connection: Any,
    inspector: Any,
    members: dict[str, set[str]],
    draft_owners: dict[tuple[str, str], set[str]],
    unresolved: list[str],
) -> None:
    """Add ownership fields to legacy JSON-only quality records."""

    rule_owners: dict[tuple[str, str], str] = {}
    if inspector.has_table("quality_alert_rules"):
        rows = connection.execute(
            sa.text("SELECT tenant_id, rule_id, agent_name, payload FROM quality_alert_rules")
        ).mappings()
        for row in rows:
            tenant_id = str(row["tenant_id"])
            payload = dict(row["payload"])
            owner = _choose_owner(
                tenant_id=tenant_id,
                direct=_payload_owner(payload, "createdBy", "created_by"),
                candidates=draft_owners.get((tenant_id, str(row["agent_name"])), set()),
                members=members,
            )
            if owner is None:
                unresolved.append(f"quality_alert_rules:{tenant_id}:{row['rule_id']}")
                continue
            rule_owners[(tenant_id, str(row["rule_id"]))] = owner
            if "createdBy" not in payload:
                payload["createdBy"] = owner
                connection.execute(
                    sa.text(
                        "UPDATE quality_alert_rules SET payload = :payload "
                        "WHERE tenant_id = :tenant AND rule_id = :resource"
                    ).bindparams(sa.bindparam("payload", type_=sa.JSON())),
                    {
                        "payload": payload,
                        "tenant": tenant_id,
                        "resource": row["rule_id"],
                    },
                )

    if inspector.has_table("quality_alert_incidents"):
        rows = connection.execute(
            sa.text(
                "SELECT tenant_id, incident_id, agent_name, payload FROM quality_alert_incidents"
            )
        ).mappings()
        for row in rows:
            tenant_id = str(row["tenant_id"])
            payload = dict(row["payload"])
            rule_id = str(payload.get("ruleId") or payload.get("rule_id") or "")
            direct = _payload_owner(payload, "ownerUserId", "owner_user_id")
            if direct is None and rule_id:
                direct = rule_owners.get((tenant_id, rule_id))
            owner = _choose_owner(
                tenant_id=tenant_id,
                direct=direct,
                candidates=draft_owners.get((tenant_id, str(row["agent_name"])), set()),
                members=members,
            )
            if owner is None:
                unresolved.append(f"quality_alert_incidents:{tenant_id}:{row['incident_id']}")
                continue
            if "ownerUserId" not in payload:
                payload["ownerUserId"] = owner
                connection.execute(
                    sa.text(
                        "UPDATE quality_alert_incidents SET payload = :payload "
                        "WHERE tenant_id = :tenant AND incident_id = :resource"
                    ).bindparams(sa.bindparam("payload", type_=sa.JSON())),
                    {
                        "payload": payload,
                        "tenant": tenant_id,
                        "resource": row["incident_id"],
                    },
                )

    dataset_owners: dict[tuple[str, str, int], str] = {}
    if inspector.has_table("eval_dataset_versions"):
        rows = connection.execute(
            sa.text("SELECT tenant_id, dataset_id, version, payload FROM eval_dataset_versions")
        ).mappings()
        for row in rows:
            owner = _payload_owner(row["payload"], "createdBy", "created_by")
            if owner:
                dataset_owners[
                    (str(row["tenant_id"]), str(row["dataset_id"]), int(row["version"]))
                ] = owner

    if inspector.has_table("quality_dataset_projections"):
        rows = connection.execute(
            sa.text("SELECT tenant_id, projection_id, payload FROM quality_dataset_projections")
        ).mappings()
        for row in rows:
            tenant_id = str(row["tenant_id"])
            payload = dict(row["payload"])
            direct = _payload_owner(payload, "createdBy", "created_by")
            if direct is None:
                dataset_id = str(payload.get("datasetId") or payload.get("dataset_id") or "")
                version = int(payload.get("datasetVersion") or payload.get("dataset_version") or 0)
                direct = dataset_owners.get((tenant_id, dataset_id, version))
            owner = _choose_owner(
                tenant_id=tenant_id,
                direct=direct,
                candidates=draft_owners.get(
                    (
                        tenant_id,
                        str(payload.get("agentName") or payload.get("agent_name") or ""),
                    ),
                    set(),
                ),
                members=members,
            )
            if owner is None:
                unresolved.append(f"quality_dataset_projections:{tenant_id}:{row['projection_id']}")
                continue
            if "createdBy" not in payload:
                payload["createdBy"] = owner
                connection.execute(
                    sa.text(
                        "UPDATE quality_dataset_projections SET payload = :payload "
                        "WHERE tenant_id = :tenant AND projection_id = :resource"
                    ).bindparams(sa.bindparam("payload", type_=sa.JSON())),
                    {
                        "payload": payload,
                        "tenant": tenant_id,
                        "resource": row["projection_id"],
                    },
                )


def _tighten_constraints() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, column in _OWNER_COLUMNS.items():
        if inspector.has_table(table):
            op.alter_column(table, column, existing_type=sa.String(128), nullable=False)

    if inspector.has_table("agent_versions"):
        _replace_primary_key("agent_versions", ["tenant_id", "owner_user_id", "name", "version"])
    if inspector.has_table("agent_drafts"):
        _replace_primary_key("agent_drafts", ["tenant_id", "owner_user_id", "draft_id"])
    if inspector.has_table("mcp_credentials"):
        _replace_primary_key("mcp_credentials", ["tenant_id", "owner_user_id", "reference"])
        indexes = {item["name"] for item in inspector.get_indexes("mcp_credentials")}
        if "ix_mcp_credentials_tenant_owner_updated" not in indexes:
            op.create_index(
                "ix_mcp_credentials_tenant_owner_updated",
                "mcp_credentials",
                ["tenant_id", "owner_user_id", "updated_at"],
            )
    if inspector.has_table("eval_dataset_versions"):
        _replace_primary_key(
            "eval_dataset_versions",
            ["tenant_id", "created_by", "dataset_id", "version"],
        )
    if inspector.has_table("deployment_environments"):
        _replace_primary_key(
            "deployment_environments",
            ["tenant_id", "owner_user_id", "agent_name", "name"],
        )

    if inspector.has_table("preview_deployments"):
        constraints = {
            item["name"] for item in inspector.get_unique_constraints("preview_deployments")
        }
        if "uq_preview_deployment_idempotency" in constraints:
            op.drop_constraint(
                "uq_preview_deployment_idempotency",
                "preview_deployments",
                type_="unique",
            )
        op.create_unique_constraint(
            "uq_preview_deployment_idempotency",
            "preview_deployments",
            ["tenant_id", "requested_by", "idempotency_key"],
        )

    if inspector.has_table("deployments"):
        constraints = {item["name"] for item in inspector.get_unique_constraints("deployments")}
        if "uq_deployment_idempotency" in constraints:
            op.drop_constraint("uq_deployment_idempotency", "deployments", type_="unique")
        op.create_unique_constraint(
            "uq_deployment_idempotency",
            "deployments",
            ["tenant_id", "requested_by", "idempotency_key"],
        )

    if inspector.has_table("eval_runs"):
        constraints = {item["name"] for item in inspector.get_unique_constraints("eval_runs")}
        if "uq_eval_run_idempotency" in constraints:
            op.drop_constraint("uq_eval_run_idempotency", "eval_runs", type_="unique")
        op.create_unique_constraint(
            "uq_eval_run_idempotency",
            "eval_runs",
            ["tenant_id", "requested_by", "idempotency_key"],
        )


def upgrade() -> None:
    _add_owner_columns()
    _backfill()
    _tighten_constraints()


def downgrade() -> None:
    # Intentionally retain owner columns and widened keys during the compatible
    # rollback window. Dropping them would merge distinct users' namespaces and
    # can destroy data when two users published the same coordinate.
    pass
