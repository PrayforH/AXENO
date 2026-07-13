"""Translate AG-UI thread/run identifiers into Harness domain identifiers."""

import asyncio
from dataclasses import dataclass

from ag_ui.core import RunAgentInput, TextInputContent

from harness.application.runs import RunService
from harness.application.sessions import SessionService
from harness.core.errors import ConflictError, NotFoundError
from harness.core.models import Run


@dataclass(frozen=True)
class AguiThreadBinding:
    session_id: str
    agent_name: str
    agent_version: str


class AguiRunService:
    def __init__(self, *, sessions: SessionService, runs: RunService) -> None:
        self._sessions = sessions
        self._runs = runs
        self._bindings: dict[tuple[str, str, str], AguiThreadBinding] = {}
        self._lock = asyncio.Lock()

    async def get_binding(
        self, *, tenant_id: str, user_id: str, thread_id: str
    ) -> AguiThreadBinding:
        try:
            return self._bindings[(tenant_id, user_id, thread_id)]
        except KeyError as error:
            raise NotFoundError(f"AG-UI thread is not bound: {thread_id}") from error

    async def create_run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_name: str,
        agent_version: str,
        request: RunAgentInput,
    ) -> Run:
        binding = await self._resolve_binding(
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=request.thread_id,
            agent_name=agent_name,
            agent_version=agent_version,
        )
        return await self._runs.create(
            tenant_id,
            binding.session_id,
            request.run_id,
            input={"prompt": _latest_user_text(request)},
        )

    async def _resolve_binding(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        agent_name: str,
        agent_version: str,
    ) -> AguiThreadBinding:
        key = (tenant_id, user_id, thread_id)
        async with self._lock:
            existing = self._bindings.get(key)
            if existing is not None:
                if (existing.agent_name, existing.agent_version) != (agent_name, agent_version):
                    raise ConflictError(
                        f"AG-UI thread {thread_id} is already bound to "
                        f"{existing.agent_name}@{existing.agent_version}"
                    )
                return existing
            session = await self._sessions.create(
                tenant_id, user_id, agent_name, agent_version
            )
            binding = AguiThreadBinding(
                session_id=session.session_id,
                agent_name=agent_name,
                agent_version=agent_version,
            )
            self._bindings[key] = binding
            return binding


def _latest_user_text(request: RunAgentInput) -> str:
    for message in reversed(request.messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            return content
        return "\n".join(item.text for item in content if isinstance(item, TextInputContent))
    return ""
