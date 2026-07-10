"""Session lifecycle use cases."""

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
    ) -> None:
        self._registry = registry
        self._sessions = sessions
        self._clock = clock
        self._id_generator = id_generator

    async def create(
        self,
        tenant_id: str,
        user_id: str,
        agent_name: str,
        agent_version: str,
    ) -> Session:
        version = await self._registry.get(tenant_id, agent_name, agent_version)
        if version.status is not AgentVersionStatus.PUBLISHED:
            raise ConflictError("sessions can only use a published Agent version")
        session = Session(
            session_id=self._id_generator("session"),
            tenant_id=tenant_id,
            user_id=user_id,
            agent_name=agent_name,
            agent_version=agent_version,
            created_at=self._clock(),
        )
        await self._sessions.add(session)
        return session

    async def get(self, tenant_id: str, session_id: str) -> Session:
        return await self._sessions.get(tenant_id, session_id)

