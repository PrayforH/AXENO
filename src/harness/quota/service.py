from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from uuid import uuid4

from harness.auth.audit import AuditService
from harness.quota.models import (
    CostState,
    QuotaConstraint,
    QuotaPolicy,
    QuotaResource,
    QuotaScope,
    QuotaUsageView,
    ReplaceQuotaPolicyRequest,
    ReservationState,
    ResourceReservation,
    UsageLedgerEntry,
)
from harness.quota.repositories import QuotaRepository

DEFAULT_LIMITS: dict[QuotaResource, int] = {
    QuotaResource.CONCURRENT_RUNS: 20,
    QuotaResource.CONCURRENT_SUBAGENTS: 50,
    QuotaResource.MODEL_TOKENS: 10_000_000,
    QuotaResource.MODEL_COST_MICRO_USD: 1_000_000_000,
    QuotaResource.MCP_REQUESTS: 50,
    QuotaResource.ARTIFACT_BYTES: 5 * 1024 * 1024 * 1024,
    QuotaResource.SNAPSHOT_BYTES: 20 * 1024 * 1024 * 1024,
    QuotaResource.ACTIVE_PREVIEWS: 10,
    QuotaResource.DEPLOYMENT_PROMOTIONS: 100,
}

_ACTIVE_RESOURCES = frozenset(
    {
        QuotaResource.CONCURRENT_RUNS,
        QuotaResource.CONCURRENT_SUBAGENTS,
        QuotaResource.ACTIVE_PREVIEWS,
    }
)


def _default_id_generator(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class QuotaService:
    def __init__(
        self,
        repository: QuotaRepository,
        *,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_generator = id_generator or _default_id_generator

    @staticmethod
    def micro_usd(value: float) -> int:
        return int(
            (Decimal(str(value)) * Decimal(1_000_000)).quantize(
                Decimal("1"), rounding=ROUND_CEILING
            )
        )

    def _window_key(self, resource: QuotaResource, at: datetime) -> str:
        if resource in _ACTIVE_RESOURCES:
            return "active"
        if resource is QuotaResource.MCP_REQUESTS:
            return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return at.astimezone(UTC).strftime("%Y-%m")

    def _builtin_policy(self, tenant_id: str) -> QuotaPolicy:
        return QuotaPolicy(
            tenantId=tenant_id,
            policyId="tenant-default",
            revision=0,
            scope=QuotaScope(),
            limits=DEFAULT_LIMITS,
            updatedBy="platform-default",
            updatedAt=datetime(1970, 1, 1, tzinfo=UTC),
        )

    async def list_policies(self, tenant_id: str) -> tuple[QuotaPolicy, ...]:
        stored = tuple(await self._repository.list_policies(tenant_id))
        has_global = any(policy.scope.key == QuotaScope().key for policy in stored)
        if not has_global:
            return (self._builtin_policy(tenant_id), *stored)
        return tuple(
            policy.model_copy(
                update={"limits": {**DEFAULT_LIMITS, **policy.limits}}
            )
            if policy.scope.key == QuotaScope().key
            else policy
            for policy in stored
        )

    async def replace_policy(
        self,
        *,
        tenant_id: str,
        user_id: str,
        policy_id: str,
        request: ReplaceQuotaPolicyRequest,
    ) -> QuotaPolicy:
        now = self._clock()
        policy = QuotaPolicy(
            tenantId=tenant_id,
            policyId=policy_id,
            revision=request.expected_revision + 1,
            scope=request.scope,
            limits=request.limits,
            updatedBy=user_id,
            updatedAt=now,
        )
        replaced = await self._repository.replace_policy(
            policy, expected_revision=request.expected_revision
        )
        if self._audit is not None:
            await self._audit.record(
                tenant_id=tenant_id,
                user_id=user_id,
                action="quota.policy.replace",
                resource_type="quota_policy",
                resource_id=policy_id,
                outcome="success",
                details={
                    "revision": replaced.revision,
                    "scope": replaced.scope.model_dump(mode="json", by_alias=True),
                    "resources": sorted(item.value for item in replaced.limits),
                },
            )
        return replaced

    async def _constraints(
        self,
        tenant_id: str,
        resource: QuotaResource,
        *,
        agent_name: str | None,
        environment: str | None,
    ) -> tuple[QuotaConstraint, ...]:
        # The synthetic tenant default remains a fallback for resources omitted
        # by a managed partial policy. The management view still shows only one
        # global policy, while admission receives a complete effective policy.
        policies = (
            self._builtin_policy(tenant_id),
            *await self._repository.list_policies(tenant_id),
        )
        selected: dict[str, QuotaPolicy] = {}
        for policy in policies:
            scope = policy.scope
            if scope.agent_name is not None and scope.agent_name != agent_name:
                continue
            if scope.environment is not None and scope.environment != environment:
                continue
            if resource not in policy.limits:
                continue
            current = selected.get(scope.key)
            if current is None or policy.revision > current.revision:
                selected[scope.key] = policy
        return tuple(
            QuotaConstraint(scopeKey=scope_key, limit=policy.limits[resource])
            for scope_key, policy in sorted(selected.items())
        )

    async def reserve(
        self,
        *,
        tenant_id: str,
        resource: QuotaResource,
        amount: int,
        subject_id: str,
        idempotency_key: str,
        agent_name: str | None = None,
        environment: str | None = None,
        ttl_seconds: int = 3600,
    ) -> ResourceReservation:
        if amount < 1:
            raise ValueError("quota reservation amount must be positive")
        now = self._clock()
        constraints = await self._constraints(
            tenant_id,
            resource,
            agent_name=agent_name,
            environment=environment,
        )
        reservation = ResourceReservation(
            tenantId=tenant_id,
            reservationId=self._id_generator("quota"),
            idempotencyKey=idempotency_key,
            resource=resource,
            amount=amount,
            constraints=constraints,
            agentName=agent_name,
            environment=environment,
            subjectId=subject_id,
            state=ReservationState.ACTIVE,
            createdAt=now,
            expiresAt=now + timedelta(seconds=ttl_seconds),
        )
        return await self._repository.reserve(
            reservation, window_key=self._window_key(resource, now)
        )

    async def commit(
        self, reservation: ResourceReservation, *, amount: int | None = None
    ) -> ResourceReservation:
        committed_amount = reservation.amount if amount is None else amount
        now = self._clock()
        ledger = UsageLedgerEntry(
            tenantId=reservation.tenant_id,
            entryId=self._id_generator("usage"),
            reservationId=reservation.reservation_id,
            resource=reservation.resource,
            amount=committed_amount,
            agentName=reservation.agent_name,
            environment=reservation.environment,
            subjectId=reservation.subject_id,
            occurredAt=now,
        )
        return await self._repository.commit(
            reservation.tenant_id,
            reservation.reservation_id,
            amount=committed_amount,
            window_key=self._window_key(reservation.resource, reservation.created_at),
            ledger=ledger,
        )

    async def release(
        self,
        reservation: ResourceReservation,
        *,
        expired: bool = False,
    ) -> ResourceReservation:
        return await self._repository.release(
            reservation.tenant_id,
            reservation.reservation_id,
            state=(ReservationState.EXPIRED if expired else ReservationState.RELEASED),
            window_key=self._window_key(reservation.resource, reservation.created_at),
        )

    async def consume(
        self,
        *,
        tenant_id: str,
        resource: QuotaResource,
        amount: int,
        subject_id: str,
        idempotency_key: str,
        agent_name: str | None = None,
        environment: str | None = None,
    ) -> ResourceReservation:
        reservation = await self.reserve(
            tenant_id=tenant_id,
            resource=resource,
            amount=amount,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            agent_name=agent_name,
            environment=environment,
        )
        return await self.commit(reservation)

    async def admit_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        agent_name: str,
        environment: str | None,
        max_budget_usd: float | None,
        max_model_tokens: int | None,
        ttl_seconds: int,
    ) -> tuple[ResourceReservation, ...]:
        admitted: list[ResourceReservation] = []
        try:
            admitted.append(
                await self.reserve(
                    tenant_id=tenant_id,
                    resource=QuotaResource.CONCURRENT_RUNS,
                    amount=1,
                    subject_id=run_id,
                    idempotency_key=f"run:{run_id}:concurrency",
                    agent_name=agent_name,
                    environment=environment,
                    ttl_seconds=ttl_seconds,
                )
            )
            if max_budget_usd is not None:
                admitted.append(
                    await self.reserve(
                        tenant_id=tenant_id,
                        resource=QuotaResource.MODEL_COST_MICRO_USD,
                        amount=self.micro_usd(max_budget_usd),
                        subject_id=run_id,
                        idempotency_key=f"run:{run_id}:cost",
                        agent_name=agent_name,
                        environment=environment,
                        ttl_seconds=ttl_seconds,
                    )
                )
            if max_model_tokens is not None:
                admitted.append(
                    await self.reserve(
                        tenant_id=tenant_id,
                        resource=QuotaResource.MODEL_TOKENS,
                        amount=max_model_tokens,
                        subject_id=run_id,
                        idempotency_key=f"run:{run_id}:tokens",
                        agent_name=agent_name,
                        environment=environment,
                        ttl_seconds=ttl_seconds,
                    )
                )
        except Exception:
            for reservation in admitted:
                await self.release(reservation)
            raise
        return tuple(admitted)

    async def ensure_run_admitted(
        self,
        *,
        tenant_id: str,
        run_id: str,
        agent_name: str,
        environment: str | None,
        max_budget_usd: float | None = None,
        max_model_tokens: int | None = None,
        ttl_seconds: int,
    ) -> tuple[ResourceReservation, ...]:
        requested = [
            (QuotaResource.CONCURRENT_RUNS, 1, f"run:{run_id}:concurrency")
        ]
        if max_budget_usd is not None:
            requested.append(
                (
                    QuotaResource.MODEL_COST_MICRO_USD,
                    self.micro_usd(max_budget_usd),
                    f"run:{run_id}:cost",
                )
            )
        if max_model_tokens is not None:
            requested.append(
                (
                    QuotaResource.MODEL_TOKENS,
                    max_model_tokens,
                    f"run:{run_id}:tokens",
                )
            )
        admitted: list[ResourceReservation] = []
        created: list[ResourceReservation] = []
        try:
            for resource, amount, idempotency_key in requested:
                existing = await self._repository.get_reservation(
                    tenant_id, idempotency_key
                )
                if existing is not None:
                    admitted.append(existing)
                    continue
                reservation = await self.reserve(
                    tenant_id=tenant_id,
                    resource=resource,
                    amount=amount,
                    subject_id=run_id,
                    idempotency_key=idempotency_key,
                    agent_name=agent_name,
                    environment=environment,
                    ttl_seconds=ttl_seconds,
                )
                admitted.append(reservation)
                created.append(reservation)
        except Exception:
            for reservation in created:
                await self.release(reservation)
            raise
        return tuple(admitted)

    async def record_run_result(
        self,
        *,
        tenant_id: str,
        run_id: str,
        agent_name: str,
        environment: str | None,
        usage: dict[str, object] | None,
        total_cost_usd: object,
    ) -> None:
        tokens = 0
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            value = (usage or {}).get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                tokens += value
        token_reservation = await self._repository.get_reservation(
            tenant_id, f"run:{run_id}:tokens"
        )
        if token_reservation is not None:
            await self.commit(token_reservation, amount=tokens)
        elif tokens:
            await self.consume(
                tenant_id=tenant_id,
                resource=QuotaResource.MODEL_TOKENS,
                amount=tokens,
                subject_id=run_id,
                idempotency_key=f"run:{run_id}:actual-tokens",
                agent_name=agent_name,
                environment=environment,
            )
        cost_reservation = await self._repository.get_reservation(tenant_id, f"run:{run_id}:cost")
        if isinstance(total_cost_usd, (int, float)) and not isinstance(total_cost_usd, bool):
            amount = self.micro_usd(float(total_cost_usd))
            if cost_reservation is not None:
                await self.commit(cost_reservation, amount=amount)
            elif amount:
                await self.consume(
                    tenant_id=tenant_id,
                    resource=QuotaResource.MODEL_COST_MICRO_USD,
                    amount=amount,
                    subject_id=run_id,
                    idempotency_key=f"run:{run_id}:actual-cost",
                    agent_name=agent_name,
                    environment=environment,
                )
            return
        if cost_reservation is not None:
            await self.release(cost_reservation)
        await self._repository.add_ledger(
            UsageLedgerEntry(
                tenantId=tenant_id,
                entryId=self._id_generator("usage"),
                resource=QuotaResource.MODEL_COST_MICRO_USD,
                amount=None,
                costState=CostState.UNKNOWN,
                agentName=agent_name,
                environment=environment,
                subjectId=run_id,
                occurredAt=self._clock(),
            )
        )

    async def release_subject(self, tenant_id: str, subject_id: str) -> int:
        reservations = await self._repository.list_active_reservations(tenant_id)
        released = 0
        for reservation in reservations:
            if reservation.subject_id != subject_id:
                continue
            await self.release(reservation)
            released += 1
        return released

    async def release_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> ResourceReservation | None:
        reservation = await self._repository.get_reservation(
            tenant_id, idempotency_key
        )
        if reservation is None or reservation.state is not ReservationState.ACTIVE:
            return reservation
        return await self.release(reservation)

    async def reap_expired(self, tenant_id: str) -> int:
        now = self._clock()
        reservations = await self._repository.list_active_reservations(tenant_id)
        expired = 0
        for reservation in reservations:
            if reservation.expires_at > now:
                continue
            await self.release(reservation, expired=True)
            expired += 1
        return expired

    async def reap_expired_all(self, *, limit: int = 200) -> int:
        reservations = await self._repository.list_expired_active(self._clock(), limit=limit)
        released = 0
        for reservation in reservations:
            await self.release(reservation, expired=True)
            released += 1
        return released

    async def usage(self, tenant_id: str) -> QuotaUsageView:
        ledger = tuple(await self._repository.list_ledger(tenant_id))
        return QuotaUsageView(
            policies=await self.list_policies(tenant_id),
            counters=tuple(await self._repository.list_counters(tenant_id)),
            activeReservations=tuple(await self._repository.list_active_reservations(tenant_id)),
            unknownCostEntries=sum(
                entry.resource is QuotaResource.MODEL_COST_MICRO_USD
                and entry.cost_state is CostState.UNKNOWN
                for entry in ledger
            ),
        )
