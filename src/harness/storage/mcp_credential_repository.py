"""PostgreSQL persistence for encrypted Studio MCP credentials."""

from sqlalchemy import select

from harness.storage.database import SessionFactory
from harness.storage.models import McpCredentialRow
from harness.studio.mcp_credential_store import StoredMcpCredential


def _value(row: McpCredentialRow) -> StoredMcpCredential:
    return StoredMcpCredential(
        tenant_id=row.tenant_id,
        owner_user_id=row.owner_user_id,
        reference=row.reference,
        revision=row.revision,
        key_names=tuple(str(item) for item in row.key_names),
        ciphertext=row.ciphertext,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


class PostgresMcpCredentialRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def get(
        self, tenant_id: str, owner_user_id: str, reference: str
    ) -> StoredMcpCredential | None:
        async with self._sessions() as session:
            row = await session.get(McpCredentialRow, (tenant_id, owner_user_id, reference))
            return _value(row) if row is not None else None

    async def list_for_user(
        self, tenant_id: str, owner_user_id: str
    ) -> tuple[StoredMcpCredential, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(McpCredentialRow)
                    .where(
                        McpCredentialRow.tenant_id == tenant_id,
                        McpCredentialRow.owner_user_id == owner_user_id,
                    )
                    .order_by(McpCredentialRow.reference)
                )
            ).all()
            return tuple(_value(row) for row in rows)

    async def upsert(self, value: StoredMcpCredential) -> StoredMcpCredential:
        async with self._sessions() as session:
            row = await session.get(
                McpCredentialRow,
                (value.tenant_id, value.owner_user_id, value.reference),
            )
            if row is None:
                row = McpCredentialRow(
                    tenant_id=value.tenant_id,
                    owner_user_id=value.owner_user_id,
                    reference=value.reference,
                    revision=1,
                    key_names=list(value.key_names),
                    ciphertext=value.ciphertext,
                    updated_by=value.updated_by,
                    updated_at=value.updated_at,
                )
                session.add(row)
            else:
                row.revision += 1
                row.key_names = list(value.key_names)
                row.ciphertext = value.ciphertext
                row.updated_by = value.updated_by
                row.updated_at = value.updated_at
            await session.commit()
            await session.refresh(row)
            return _value(row)

    async def delete(self, tenant_id: str, owner_user_id: str, reference: str) -> bool:
        async with self._sessions() as session:
            row = await session.get(McpCredentialRow, (tenant_id, owner_user_id, reference))
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True
