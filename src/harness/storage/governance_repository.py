from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError

from harness.core.errors import ConflictError, NotFoundError
from harness.governance.models import (
    CredentialConnection,
    GovernedPolicyProfile,
    PolicyPublication,
)
from harness.storage.database import SessionFactory
from harness.storage.models import (
    CredentialConnectionRow,
    GovernedPolicyPublicationRow,
    GovernedPolicyRow,
)


class PostgresGovernanceRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def add_connection(self, value: CredentialConnection) -> None:
        async with self._sessions() as db:
            db.add(
                CredentialConnectionRow(
                    tenant_id=value.tenant_id,
                    connection_id=value.connection_id,
                    resource_kind=value.resource_kind.value,
                    resource_reference=value.resource_reference,
                    scope=value.scope.value,
                    principal_id=value.principal_id,
                    status=value.status.value,
                    revision=value.revision,
                    updated_at=value.updated_at,
                    payload=value.model_dump(mode="json", by_alias=True),
                )
            )
            try:
                await db.commit()
            except IntegrityError as error:
                await db.rollback()
                raise ConflictError(
                    f"credential connection already exists: {value.connection_id}"
                ) from error

    async def get_connection(
        self, tenant_id: str, connection_id: str
    ) -> CredentialConnection:
        async with self._sessions() as db:
            row = await db.get(CredentialConnectionRow, (tenant_id, connection_id))
            if row is None:
                raise NotFoundError(
                    f"credential connection not found: {connection_id}"
                )
            return CredentialConnection.model_validate(row.payload)

    async def list_connections(
        self,
        tenant_id: str,
        *,
        resource_kind: str | None = None,
        resource_reference: str | None = None,
    ) -> Sequence[CredentialConnection]:
        statement = select(CredentialConnectionRow).where(
            CredentialConnectionRow.tenant_id == tenant_id
        )
        if resource_kind is not None:
            statement = statement.where(
                CredentialConnectionRow.resource_kind == resource_kind
            )
        if resource_reference is not None:
            statement = statement.where(
                CredentialConnectionRow.resource_reference == resource_reference
            )
        statement = statement.order_by(CredentialConnectionRow.connection_id)
        async with self._sessions() as db:
            rows = (await db.scalars(statement)).all()
        return tuple(
            CredentialConnection.model_validate(row.payload) for row in rows
        )

    async def compare_and_set_connection(
        self, expected_revision: int, value: CredentialConnection
    ) -> bool:
        if value.revision != expected_revision + 1:
            raise ConflictError("credential connection revision must increment by one")
        statement = (
            update(CredentialConnectionRow)
            .where(
                CredentialConnectionRow.tenant_id == value.tenant_id,
                CredentialConnectionRow.connection_id == value.connection_id,
                CredentialConnectionRow.revision == expected_revision,
            )
            .values(
                resource_kind=value.resource_kind.value,
                resource_reference=value.resource_reference,
                scope=value.scope.value,
                principal_id=value.principal_id,
                status=value.status.value,
                revision=value.revision,
                updated_at=value.updated_at,
                payload=value.model_dump(mode="json", by_alias=True),
            )
        )
        async with self._sessions() as db:
            result = await db.execute(statement)
            await db.commit()
            return bool(cast(CursorResult[Any], result).rowcount)

    async def add_policy(self, value: GovernedPolicyProfile) -> None:
        async with self._sessions() as db:
            db.add(
                GovernedPolicyRow(
                    tenant_id=value.tenant_id,
                    policy_id=value.policy_id,
                    revision=value.revision,
                    published_revision=value.published_revision,
                    published_hash=value.published_hash,
                    updated_at=value.updated_at,
                    payload=value.model_dump(mode="json", by_alias=True),
                )
            )
            try:
                await db.commit()
            except IntegrityError as error:
                await db.rollback()
                raise ConflictError(
                    f"governed policy already exists: {value.policy_id}"
                ) from error

    async def get_policy(
        self, tenant_id: str, policy_id: str
    ) -> GovernedPolicyProfile:
        async with self._sessions() as db:
            row = await db.get(GovernedPolicyRow, (tenant_id, policy_id))
            if row is None:
                raise NotFoundError(f"governed policy not found: {policy_id}")
            return GovernedPolicyProfile.model_validate(row.payload)

    async def list_policies(
        self, tenant_id: str
    ) -> Sequence[GovernedPolicyProfile]:
        statement = (
            select(GovernedPolicyRow)
            .where(GovernedPolicyRow.tenant_id == tenant_id)
            .order_by(GovernedPolicyRow.policy_id)
        )
        async with self._sessions() as db:
            rows = (await db.scalars(statement)).all()
        return tuple(
            GovernedPolicyProfile.model_validate(row.payload) for row in rows
        )

    async def compare_and_set_policy(
        self, expected_revision: int, value: GovernedPolicyProfile
    ) -> bool:
        if value.revision != expected_revision + 1:
            raise ConflictError("governed policy revision must increment by one")
        statement = (
            update(GovernedPolicyRow)
            .where(
                GovernedPolicyRow.tenant_id == value.tenant_id,
                GovernedPolicyRow.policy_id == value.policy_id,
                GovernedPolicyRow.revision == expected_revision,
            )
            .values(
                revision=value.revision,
                published_revision=value.published_revision,
                published_hash=value.published_hash,
                updated_at=value.updated_at,
                payload=value.model_dump(mode="json", by_alias=True),
            )
        )
        async with self._sessions() as db:
            result = await db.execute(statement)
            await db.commit()
            return bool(cast(CursorResult[Any], result).rowcount)

    async def publish_policy(
        self,
        *,
        expected_revision: int,
        profile: GovernedPolicyProfile,
        publication: PolicyPublication,
    ) -> bool:
        statement = (
            update(GovernedPolicyRow)
            .where(
                GovernedPolicyRow.tenant_id == profile.tenant_id,
                GovernedPolicyRow.policy_id == profile.policy_id,
                GovernedPolicyRow.revision == expected_revision,
            )
            .values(
                published_revision=profile.published_revision,
                published_hash=profile.published_hash,
                updated_at=profile.updated_at,
                payload=profile.model_dump(mode="json", by_alias=True),
            )
        )
        async with self._sessions() as db:
            result = await db.execute(statement)
            if not cast(CursorResult[Any], result).rowcount:
                await db.rollback()
                return False
            db.add(
                GovernedPolicyPublicationRow(
                    tenant_id=publication.tenant_id,
                    policy_id=publication.policy_id,
                    revision=publication.revision,
                    content_hash=publication.content_hash,
                    published_at=publication.published_at,
                    payload=publication.model_dump(mode="json", by_alias=True),
                )
            )
            try:
                await db.commit()
            except IntegrityError as error:
                await db.rollback()
                raise ConflictError(
                    "governed policy publication already exists: "
                    f"{publication.policy_id}@{publication.revision}"
                ) from error
            return True

    async def get_publication(
        self, tenant_id: str, policy_id: str, revision: int
    ) -> PolicyPublication:
        async with self._sessions() as db:
            row = await db.get(
                GovernedPolicyPublicationRow,
                (tenant_id, policy_id, revision),
            )
            if row is None:
                raise NotFoundError(
                    f"governed policy publication not found: {policy_id}@{revision}"
                )
            return PolicyPublication.model_validate(row.payload)

    async def list_publications(
        self, tenant_id: str, policy_id: str
    ) -> Sequence[PolicyPublication]:
        statement = (
            select(GovernedPolicyPublicationRow)
            .where(
                GovernedPolicyPublicationRow.tenant_id == tenant_id,
                GovernedPolicyPublicationRow.policy_id == policy_id,
            )
            .order_by(GovernedPolicyPublicationRow.revision.desc())
        )
        async with self._sessions() as db:
            rows = (await db.scalars(statement)).all()
        return tuple(PolicyPublication.model_validate(row.payload) for row in rows)
