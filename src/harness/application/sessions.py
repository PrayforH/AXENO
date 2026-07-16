"""Session lifecycle use cases."""

from harness.application.agent_assets import resolve_published_agent_versions
from harness.application.types import Clock, IdGenerator
from harness.core.errors import ConflictError
from harness.core.models import AgentVersionStatus, Session
from harness.core.ports import AgentRegistry, SessionRepository


class SessionService:
    def __init__(
        self,
        registry: AgentRegistry,
        sessions: SessionRepository,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        require_published_dependencies: bool = False,
    ) -> None:
        self._registry = registry
        self._sessions = sessions
        self._clock = clock
        self._id_generator = id_generator
        self._require_published_dependencies = require_published_dependencies

    async def create(
        self,
        tenant_id: str,
        user_id: str,
        agent_name: str,
        agent_version: str,
        *,
        session_id: str | None = None,
    ) -> Session:
        version = await self._registry.get(tenant_id, agent_name, agent_version)
        if version.status is not AgentVersionStatus.PUBLISHED:
            raise ConflictError("sessions can only use a published Agent version")
        if self._require_published_dependencies:
            await resolve_published_agent_versions(
                self._registry,
                tenant_id=tenant_id,
                agent_name=agent_name,
                agent_version=agent_version,
            )
        session = Session(
            session_id=session_id or self._id_generator("session"),
            tenant_id=tenant_id,
            user_id=user_id,
            agent_name=agent_name,
            agent_version=agent_version,
            created_at=self._clock(),
        )
        try:
            await self._sessions.add(session)
        except ConflictError as error:
            if session_id is None:
                raise
            existing = await self._sessions.get(tenant_id, session_id)
            if (
                existing.user_id != user_id
                or existing.agent_name != agent_name
                or existing.agent_version != agent_version
            ):
                raise ConflictError(
                    "deterministic Session ID was reused for another Eval Case"
                ) from error
            return existing
        return session

    async def get(self, tenant_id: str, session_id: str) -> Session:
        return await self._sessions.get(tenant_id, session_id)
