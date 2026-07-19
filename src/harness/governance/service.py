from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from harness.auth.audit import AuditService
from harness.core.errors import ConflictError, NotFoundError
from harness.core.models import ExecutionIdentity
from harness.execution.credentials import (
    CredentialConnectionGrant,
    CredentialLeaseError,
    CredentialResourceKind,
)
from harness.governance.models import (
    ConnectionScope,
    ConnectionStatus,
    CreateCredentialConnectionRequest,
    CreateGovernedPolicyRequest,
    CredentialConnection,
    GovernedCallRule,
    GovernedPolicyProfile,
    GovernedResultRule,
    PolicyImpactItem,
    PolicyImpactPreview,
    PolicyPublication,
    PolicyScenario,
    PolicySimulationResult,
    PreviewPolicyImpactRequest,
    ReplaceCredentialConnectionRequest,
    ReplaceGovernedPolicyRequest,
)
from harness.governance.repositories import GovernanceRepository
from harness.policy.models import PolicyContext
from harness.policy.profiles import PolicyProfileRegistry
from harness.policy.results import ResultPolicyEngine
from harness.policy.rules import PolicyEngine
from harness.policy.runtime import ResolvedPolicy


class GovernanceService:
    def __init__(
        self,
        repository: GovernanceRepository,
        *,
        static_profiles: PolicyProfileRegistry,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self._static_profiles = static_profiles
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_connections(
        self,
        tenant_id: str,
        *,
        resource_kind: CredentialResourceKind | None = None,
        resource_reference: str | None = None,
    ) -> Sequence[CredentialConnection]:
        return await self.repository.list_connections(
            tenant_id,
            resource_kind=resource_kind.value if resource_kind is not None else None,
            resource_reference=resource_reference,
        )

    async def create_connection(
        self,
        tenant_id: str,
        actor_id: str,
        request: CreateCredentialConnectionRequest,
    ) -> CredentialConnection:
        existing = await self.repository.list_connections(
            tenant_id,
            resource_kind=request.resource_kind.value,
            resource_reference=request.resource_reference,
        )
        if any(
            item.status is ConnectionStatus.ACTIVE
            and item.scope is request.scope
            and item.principal_id == request.principal_id
            for item in existing
        ):
            raise ConflictError(
                "an active credential connection already exists for this resource and principal"
            )
        now = self._clock()
        value = CredentialConnection(
            tenant_id=tenant_id,
            connection_id=request.connection_id,
            display_name=request.display_name,
            resource_kind=request.resource_kind,
            resource_reference=request.resource_reference,
            scope=request.scope,
            principal_id=request.principal_id,
            secret_reference=request.secret_reference,
            required_keys=request.required_keys,
            revision=1,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        await self.repository.add_connection(value)
        await self._record(
            tenant_id,
            actor_id,
            "credential.connection.create",
            value.connection_id,
            {
                "resource_kind": value.resource_kind.value,
                "resource_reference": value.resource_reference,
                "scope": value.scope.value,
                "principal_id": value.principal_id,
                "required_keys": list(value.required_keys),
            },
        )
        return value

    async def replace_connection(
        self,
        tenant_id: str,
        actor_id: str,
        connection_id: str,
        request: ReplaceCredentialConnectionRequest,
    ) -> CredentialConnection:
        current = await self.repository.get_connection(tenant_id, connection_id)
        if current.revision != request.expected_revision:
            raise ConflictError("credential connection revision changed")
        if current.status is ConnectionStatus.REVOKED:
            raise ConflictError("revoked credential connections are immutable")
        updated = current.model_copy(
            update={
                "display_name": request.display_name,
                "secret_reference": request.secret_reference,
                "required_keys": request.required_keys,
                "revision": current.revision + 1,
                "updated_by": actor_id,
                "updated_at": self._clock(),
            }
        )
        if not await self.repository.compare_and_set_connection(current.revision, updated):
            raise ConflictError("credential connection changed while it was updated")
        await self._record(
            tenant_id,
            actor_id,
            "credential.connection.update",
            connection_id,
            {"required_keys": list(updated.required_keys)},
        )
        return updated

    async def revoke_connection(
        self,
        tenant_id: str,
        actor_id: str,
        connection_id: str,
        *,
        expected_revision: int,
    ) -> CredentialConnection:
        current = await self.repository.get_connection(tenant_id, connection_id)
        if current.revision != expected_revision:
            raise ConflictError("credential connection revision changed")
        if current.status is ConnectionStatus.REVOKED:
            return current
        now = self._clock()
        revoked = current.model_copy(
            update={
                "status": ConnectionStatus.REVOKED,
                "revision": current.revision + 1,
                "updated_by": actor_id,
                "updated_at": now,
                "revoked_at": now,
            }
        )
        if not await self.repository.compare_and_set_connection(current.revision, revoked):
            raise ConflictError("credential connection changed while it was revoked")
        await self._record(
            tenant_id,
            actor_id,
            "credential.connection.revoke",
            connection_id,
            {
                "resource_kind": revoked.resource_kind.value,
                "resource_reference": revoked.resource_reference,
                "scope": revoked.scope.value,
                "principal_id": revoked.principal_id,
            },
        )
        return revoked

    async def authorize(
        self,
        identity: ExecutionIdentity,
        resource_kind: CredentialResourceKind,
        resource_reference: str,
    ) -> CredentialConnectionGrant | None:
        candidates = await self.repository.list_connections(
            identity.tenant_id,
            resource_kind=resource_kind.value,
            resource_reference=resource_reference,
        )
        if not candidates:
            return None
        matches = [
            connection
            for connection in candidates
            if connection.status is ConnectionStatus.ACTIVE
            and self._connection_matches(connection, identity)
        ]
        if not matches:
            raise CredentialLeaseError("managed credential connection is not authorized")
        selected = max(
            matches,
            key=lambda item: (
                1 if item.scope is ConnectionScope.TEAM else 2,
                item.connection_id,
            ),
        )
        return self._grant(selected)

    async def validate_connection(
        self,
        connection_id: str,
        identity: ExecutionIdentity,
        resource_kind: CredentialResourceKind,
        resource_reference: str,
    ) -> CredentialConnectionGrant:
        try:
            connection = await self.repository.get_connection(
                identity.tenant_id, connection_id
            )
        except NotFoundError as error:
            raise CredentialLeaseError("credential connection no longer exists") from error
        if (
            connection.status is not ConnectionStatus.ACTIVE
            or connection.resource_kind is not resource_kind
            or connection.resource_reference != resource_reference
            or not self._connection_matches(connection, identity)
        ):
            raise CredentialLeaseError("credential connection is no longer authorized")
        return self._grant(connection)

    async def create_policy(
        self,
        tenant_id: str,
        actor_id: str,
        request: CreateGovernedPolicyRequest,
    ) -> GovernedPolicyProfile:
        now = self._clock()
        value = GovernedPolicyProfile(
            tenant_id=tenant_id,
            policy_id=request.policy_id,
            display_name=request.display_name,
            description=request.description,
            call_rules=request.call_rules,
            result_rules=request.result_rules,
            revision=1,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        await self.repository.add_policy(value)
        await self._record(
            tenant_id,
            actor_id,
            "policy.profile.create",
            value.policy_id,
            {
                "revision": value.revision,
                "call_rule_count": len(value.call_rules),
                "result_rule_count": len(value.result_rules),
            },
        )
        return value

    async def replace_policy(
        self,
        tenant_id: str,
        actor_id: str,
        policy_id: str,
        request: ReplaceGovernedPolicyRequest,
    ) -> GovernedPolicyProfile:
        current = await self.repository.get_policy(tenant_id, policy_id)
        if current.revision != request.expected_revision:
            raise ConflictError("governed policy revision changed")
        updated = current.model_copy(
            update={
                "display_name": request.display_name,
                "description": request.description,
                "call_rules": request.call_rules,
                "result_rules": request.result_rules,
                "revision": current.revision + 1,
                "updated_by": actor_id,
                "updated_at": self._clock(),
            }
        )
        if not await self.repository.compare_and_set_policy(current.revision, updated):
            raise ConflictError("governed policy changed while it was updated")
        await self._record(
            tenant_id,
            actor_id,
            "policy.profile.update",
            policy_id,
            {
                "revision": updated.revision,
                "call_rule_count": len(updated.call_rules),
                "result_rule_count": len(updated.result_rules),
            },
        )
        return updated

    async def list_policies(self, tenant_id: str) -> Sequence[GovernedPolicyProfile]:
        return await self.repository.list_policies(tenant_id)

    async def get_policy(
        self, tenant_id: str, policy_id: str
    ) -> GovernedPolicyProfile:
        return await self.repository.get_policy(tenant_id, policy_id)

    async def publish_policy(
        self,
        tenant_id: str,
        actor_id: str,
        policy_id: str,
        *,
        expected_revision: int,
    ) -> PolicyPublication:
        current = await self.repository.get_policy(tenant_id, policy_id)
        if current.revision != expected_revision:
            raise ConflictError("governed policy revision changed")
        content_hash = self._policy_hash(current)
        now = self._clock()
        publication = PolicyPublication(
            tenant_id=tenant_id,
            policy_id=policy_id,
            revision=current.revision,
            content_hash=content_hash,
            display_name=current.display_name,
            description=current.description,
            call_rules=current.call_rules,
            result_rules=current.result_rules,
            published_by=actor_id,
            published_at=now,
        )
        published_profile = current.model_copy(
            update={
                "published_revision": current.revision,
                "published_hash": content_hash,
                "updated_by": actor_id,
                "updated_at": now,
            }
        )
        if not await self.repository.publish_policy(
            expected_revision=current.revision,
            profile=published_profile,
            publication=publication,
        ):
            raise ConflictError("governed policy changed while it was published")
        await self._record(
            tenant_id,
            actor_id,
            "policy.profile.publish",
            policy_id,
            {
                "revision": publication.revision,
                "content_hash": publication.content_hash,
                "call_rule_count": len(publication.call_rules),
                "result_rule_count": len(publication.result_rules),
            },
        )
        return publication

    async def simulate_draft(
        self,
        tenant_id: str,
        policy_id: str,
        scenario: PolicyScenario,
    ) -> PolicySimulationResult:
        profile = await self.repository.get_policy(tenant_id, policy_id)
        return self._simulate(
            tenant_id,
            scenario,
            self._call_engine(profile.call_rules),
            self._result_engine(profile.result_rules),
        )

    async def preview_impact(
        self,
        tenant_id: str,
        policy_id: str,
        request: PreviewPolicyImpactRequest,
    ) -> PolicyImpactPreview:
        profile = await self.repository.get_policy(tenant_id, policy_id)
        before = await self.resolve_runtime(tenant_id, policy_id)
        after_call = self._call_engine(profile.call_rules)
        after_result = self._result_engine(profile.result_rules)
        items: list[PolicyImpactItem] = []
        for scenario in request.scenarios:
            old = self._simulate(
                tenant_id,
                scenario, before.call_policy, before.result_policy
            )
            new = self._simulate(tenant_id, scenario, after_call, after_result)
            changed = (
                old.call.decision != new.call.decision
                or old.call.rule_name != new.call.rule_name
                or old.result.trust != new.result.trust
                or old.result.rule_name != new.result.rule_name
            )
            items.append(
                PolicyImpactItem(
                    scenario_id=scenario.scenario_id,
                    before=old,
                    after=new,
                    changed=changed,
                )
            )
        return PolicyImpactPreview(
            policy_id=policy_id,
            draft_revision=profile.revision,
            published_revision=profile.published_revision,
            scenario_count=len(items),
            changed_count=sum(item.changed for item in items),
            items=tuple(items),
        )

    async def resolve_runtime(
        self, tenant_id: str, policy_id: str
    ) -> ResolvedPolicy:
        try:
            profile = await self.repository.get_policy(tenant_id, policy_id)
        except NotFoundError:
            return self._resolve_static(policy_id)
        if profile.published_revision is None:
            return self._resolve_static(policy_id)
        publication = await self.repository.get_publication(
            tenant_id,
            policy_id,
            profile.published_revision,
        )
        if publication.content_hash != profile.published_hash:
            raise ConflictError("governed policy publication hash does not match profile")
        if publication.content_hash != self._publication_hash(publication):
            raise ConflictError("governed policy publication content hash is invalid")
        return ResolvedPolicy(
            policy_id=policy_id,
            revision=publication.revision,
            content_hash=publication.content_hash,
            call_policy=self._call_engine(publication.call_rules),
            result_policy=self._result_engine(publication.result_rules),
        )

    async def list_publications(
        self, tenant_id: str, policy_id: str
    ) -> Sequence[PolicyPublication]:
        return await self.repository.list_publications(tenant_id, policy_id)

    def _resolve_static(self, policy_id: str) -> ResolvedPolicy:
        engine = self._static_profiles.resolve(policy_id)
        payload = [
            rule.model_dump(mode="json")
            for rule in engine.rules
        ]
        content_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ResolvedPolicy(
            policy_id=policy_id,
            revision=None,
            content_hash=content_hash,
            call_policy=engine,
            result_policy=ResultPolicyEngine([]),
        )

    @staticmethod
    def _connection_matches(
        connection: CredentialConnection, identity: ExecutionIdentity
    ) -> bool:
        is_workload = identity.user_id.startswith("trigger:")
        if is_workload:
            return (
                connection.scope is ConnectionScope.WORKLOAD
                and connection.principal_id == identity.user_id
            )
        if connection.scope is ConnectionScope.PERSONAL:
            return connection.principal_id == identity.user_id
        if connection.scope is ConnectionScope.TEAM:
            return connection.principal_id in identity.team_ids
        return False

    @staticmethod
    def _grant(connection: CredentialConnection) -> CredentialConnectionGrant:
        return CredentialConnectionGrant(
            connection_id=connection.connection_id,
            scope=connection.scope.value,
            principal_id=connection.principal_id,
            secret_reference=connection.secret_reference,
            required_keys=frozenset(connection.required_keys),
        )

    @staticmethod
    def _call_engine(rules: Sequence[GovernedCallRule]) -> PolicyEngine:
        return PolicyEngine([rule.to_policy_rule() for rule in rules])

    @staticmethod
    def _result_engine(rules: Sequence[GovernedResultRule]) -> ResultPolicyEngine:
        return ResultPolicyEngine([rule.to_policy_rule() for rule in rules])

    @staticmethod
    def _simulate(
        tenant_id: str,
        scenario: PolicyScenario,
        call_policy: PolicyEngine,
        result_policy: ResultPolicyEngine,
    ) -> PolicySimulationResult:
        call = call_policy.evaluate(
            PolicyContext(
                tenant_id=tenant_id,
                agent_name=scenario.agent_name,
                tool_name=scenario.tool_name,
                arguments=scenario.arguments,
                sandbox_isolation=scenario.sandbox_isolation,
                context_trust=scenario.context_trust,
            )
        )
        result = result_policy.evaluate(
            scenario.tool_name,
            agent_name=scenario.agent_name,
        )
        return PolicySimulationResult(
            scenario_id=scenario.scenario_id,
            call=call,
            result=result,
        )

    @staticmethod
    def _policy_hash(profile: GovernedPolicyProfile) -> str:
        return GovernanceService._content_hash(
            policy_id=profile.policy_id,
            display_name=profile.display_name,
            description=profile.description,
            call_rules=profile.call_rules,
            result_rules=profile.result_rules,
        )

    @staticmethod
    def _publication_hash(publication: PolicyPublication) -> str:
        return GovernanceService._content_hash(
            policy_id=publication.policy_id,
            display_name=publication.display_name,
            description=publication.description,
            call_rules=publication.call_rules,
            result_rules=publication.result_rules,
        )

    @staticmethod
    def _content_hash(
        *,
        policy_id: str,
        display_name: str,
        description: str,
        call_rules: Sequence[GovernedCallRule],
        result_rules: Sequence[GovernedResultRule],
    ) -> str:
        payload = {
            "policy_id": policy_id,
            "display_name": display_name,
            "description": description,
            "call_rules": [
                rule.model_dump(mode="json", by_alias=True)
                for rule in call_rules
            ],
            "result_rules": [
                rule.model_dump(mode="json", by_alias=True)
                for rule in result_rules
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _record(
        self,
        tenant_id: str,
        actor_id: str,
        action: str,
        resource_id: str,
        details: dict[str, object],
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            tenant_id=tenant_id,
            user_id=actor_id,
            action=action,
            resource_type="governance",
            resource_id=resource_id,
            details=details,
        )
