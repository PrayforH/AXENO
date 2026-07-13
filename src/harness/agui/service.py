"""Translate AG-UI thread/run identifiers into Harness domain identifiers."""

import asyncio
from dataclasses import dataclass
from typing import cast

from ag_ui.core import (
    BinaryInputContent,
    DocumentInputContent,
    RunAgentInput,
    TextInputContent,
)

from harness.application.input_artifacts import InputArtifactService
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
    def __init__(
        self,
        *,
        sessions: SessionService,
        runs: RunService,
        input_artifacts: InputArtifactService,
    ) -> None:
        self._sessions = sessions
        self._run_service = runs
        self._input_artifacts = input_artifacts
        self._bindings: dict[tuple[str, str, str], AguiThreadBinding] = {}
        self._run_bindings: dict[tuple[str, str, str, str], str] = {}
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
        prompt, input_artifact_ids = _latest_user_input(request)
        resolved = await self._input_artifacts.resolve_for_run(
            tenant_id=tenant_id,
            user_id=user_id,
            input_artifact_ids=input_artifact_ids,
        )
        binding = await self._resolve_binding(
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=request.thread_id,
            agent_name=agent_name,
            agent_version=agent_version,
        )
        run = await self._run_service.create(
            tenant_id,
            binding.session_id,
            request.run_id,
            input={
                "prompt": prompt,
                "input_artifact_ids": [item.input_artifact_id for item in resolved],
            },
        )
        async with self._lock:
            self._run_bindings[
                (tenant_id, user_id, request.thread_id, request.run_id)
            ] = run.run_id
        return run

    async def cancel_run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        client_run_id: str,
    ) -> Run:
        key = (tenant_id, user_id, thread_id, client_run_id)
        async with self._lock:
            run_id = self._run_bindings.get(key)
        if run_id is None:
            raise NotFoundError(
                f"AG-UI run is not bound: {thread_id}/{client_run_id}"
            )
        return await self._run_service.cancel(tenant_id, run_id)

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


def _latest_user_input(request: RunAgentInput) -> tuple[str, list[str]]:
    for message in reversed(request.messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            return content, []
        text = "\n".join(
            item.text for item in content if isinstance(item, TextInputContent)
        )
        input_artifact_ids: list[str] = []
        for item in content:
            input_artifact_id: object | None = None
            if isinstance(item, BinaryInputContent):
                input_artifact_id = item.id
            elif isinstance(item, DocumentInputContent):
                raw_metadata: object = item.metadata
                if isinstance(raw_metadata, dict):
                    metadata = cast(dict[str, object], raw_metadata)
                    input_artifact_id = metadata.get(
                        "inputArtifactId", metadata.get("input_artifact_id")
                    )
            if isinstance(input_artifact_id, str) and input_artifact_id:
                input_artifact_ids.append(input_artifact_id)
        return text, input_artifact_ids
    return "", []
