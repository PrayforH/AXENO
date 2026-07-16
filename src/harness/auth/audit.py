"""Append-only security audit service."""

from datetime import UTC, datetime
from uuid import uuid4

from harness.auth.models import AuditEntry
from harness.auth.repositories import AuditRepository


class AuditService:
    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def record(
        self,
        *,
        tenant_id: str | None,
        user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        outcome: str = "success",
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, object] | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            audit_id=f"audit_{uuid4().hex}",
            occurred_at=datetime.now(UTC),
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
        )
        await self._repository.add(entry)
        return entry

    async def list_for_tenant(self, tenant_id: str, *, limit: int = 100) -> list[AuditEntry]:
        return await self._repository.list_for_tenant(tenant_id, limit=limit)
