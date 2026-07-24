"""Translate AG-UI thread/run identifiers into Harness domain identifiers."""

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from ag_ui.core import (
    AudioInputContent,
    BinaryInputContent,
    DocumentInputContent,
    ImageInputContent,
    InputContentDataSource,
    RunAgentInput,
    TextInputContent,
    VideoInputContent,
)

from harness.adapters.memory import InMemoryAguiThreadBindingRepository
from harness.agui.task_title import (
    TaskTitleGenerator,
    summarize_task_title_from_prompts,
)
from harness.application.input_artifacts import InputArtifactService
from harness.application.runs import RunService
from harness.application.sessions import SessionService
from harness.core.errors import ConflictError, NotFoundError
from harness.core.models import AguiThreadBinding as StoredAguiThreadBinding
from harness.core.models import Run
from harness.core.ports import AguiThreadBindingRepository


@dataclass(frozen=True)
class AguiThreadBinding:
    session_id: str
    agent_name: str
    agent_version: str


@dataclass(frozen=True)
class AguiRunCreation:
    run: Run
    canonical_client_run_id: str
    reused: bool
    deduplicated: bool


class AguiRunService:
    def __init__(
        self,
        *,
        sessions: SessionService,
        runs: RunService,
        input_artifacts: InputArtifactService,
        bindings: AguiThreadBindingRepository | None = None,
        title_generator: TaskTitleGenerator | None = None,
    ) -> None:
        self._sessions = sessions
        self._run_service = runs
        self._input_artifacts = input_artifacts
        self._bindings = bindings or InMemoryAguiThreadBindingRepository()
        self._title_generator = title_generator
        self._title_tasks: set[asyncio.Task[None]] = set()
        self._title_task_keys: set[tuple[str, str, str, datetime]] = set()
        self._run_bindings: dict[tuple[str, str, str, str], str] = {}
        self._lock = asyncio.Lock()

    async def get_binding(
        self, *, tenant_id: str, user_id: str, thread_id: str
    ) -> AguiThreadBinding:
        stored = await self._bindings.get_by_thread(tenant_id, user_id, thread_id)
        session = await self._sessions.get(tenant_id, stored.session_id)
        return AguiThreadBinding(
            session_id=session.session_id,
            agent_name=session.agent_name,
            agent_version=session.agent_version,
        )

    async def list_bindings(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
        archived: bool = False,
    ) -> list[StoredAguiThreadBinding]:
        return await self._bindings.list_for_user(
            tenant_id, user_id, limit=limit, archived=archived
        )

    async def set_archived(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        archived: bool,
    ) -> StoredAguiThreadBinding:
        return await self._bindings.set_archived(
            tenant_id,
            user_id,
            thread_id,
            archived_at=datetime.now(UTC) if archived else None,
        )

    async def create_run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_name: str,
        agent_version: str,
        request: RunAgentInput,
    ) -> Run:
        return (
            await self.create_run_with_result(
                tenant_id=tenant_id,
                user_id=user_id,
                agent_name=agent_name,
                agent_version=agent_version,
                request=request,
            )
        ).run

    async def create_run_with_result(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_name: str,
        agent_version: str,
        request: RunAgentInput,
    ) -> AguiRunCreation:
        prompt, input_artifact_ids = _latest_user_input(request)
        conversation_prompts = _user_prompts(request)
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
        creation = await self._run_service.create_with_result(
            tenant_id,
            binding.session_id,
            request.run_id,
            input={
                "prompt": prompt,
                "conversation_prompts": conversation_prompts,
                "input_artifact_ids": [item.input_artifact_id for item in resolved],
                **(
                    {"required_model_capabilities": ["vision"]}
                    if any(item.media_type.startswith("image/") for item in resolved)
                    else {}
                ),
                **(
                    {"model_route_override": model_route_override}
                    if (model_route_override := _model_route_override(request)) is not None
                    else {}
                ),
            },
            deduplicate_active_input=True,
        )
        run = creation.run
        async with self._lock:
            self._run_bindings[(tenant_id, user_id, request.thread_id, request.run_id)] = run.run_id
        title_timestamp = datetime.now(UTC)
        await self._bindings.update_title(
            tenant_id,
            user_id,
            request.thread_id,
            title=summarize_task_title_from_prompts(conversation_prompts),
            source="fallback",
            generated_at=title_timestamp,
        )
        self._schedule_model_title(
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=request.thread_id,
            prompts=conversation_prompts,
            generated_at=title_timestamp,
        )
        return AguiRunCreation(
            run=run,
            canonical_client_run_id=run.idempotency_key,
            reused=not creation.created,
            deduplicated=creation.deduplicated,
        )

    async def resolve_title(self, binding: StoredAguiThreadBinding, prompts: list[str]) -> str:
        if binding.title and (
            binding.title_source == "model" or self._title_generator is None or not prompts
        ):
            return binding.title
        generated_at = binding.title_updated_at or datetime.now(UTC)
        if binding.title:
            self._schedule_model_title(
                tenant_id=binding.tenant_id,
                user_id=binding.user_id,
                thread_id=binding.thread_id,
                prompts=prompts,
                generated_at=generated_at,
            )
            return binding.title
        updated = await self._bindings.update_title(
            binding.tenant_id,
            binding.user_id,
            binding.thread_id,
            title=summarize_task_title_from_prompts(prompts),
            source="fallback",
            generated_at=generated_at,
        )
        self._schedule_model_title(
            tenant_id=binding.tenant_id,
            user_id=binding.user_id,
            thread_id=binding.thread_id,
            prompts=prompts,
            generated_at=generated_at,
        )
        return updated.title or "新任务"

    def _schedule_model_title(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        prompts: list[str],
        generated_at: datetime,
    ) -> None:
        if self._title_generator is None or not prompts:
            return
        key = (tenant_id, user_id, thread_id, generated_at)
        if key in self._title_task_keys:
            return
        self._title_task_keys.add(key)
        task = asyncio.create_task(
            self._generate_model_title(
                tenant_id=tenant_id,
                user_id=user_id,
                thread_id=thread_id,
                prompts=prompts,
                generated_at=generated_at,
            )
        )
        self._title_tasks.add(task)

        def cleanup(completed: asyncio.Task[None]) -> None:
            self._title_tasks.discard(completed)
            self._title_task_keys.discard(key)

        task.add_done_callback(cleanup)

    async def _generate_model_title(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        prompts: list[str],
        generated_at: datetime,
    ) -> None:
        assert self._title_generator is not None
        try:
            title = await self._title_generator.generate(prompts)
            await self._bindings.update_title(
                tenant_id,
                user_id,
                thread_id,
                title=title,
                source="model",
                generated_at=generated_at,
            )
        except Exception:
            # A title must never block the Agent run; the deterministic title remains valid.
            return

    async def cancel_run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        client_run_id: str,
    ) -> Run:
        run = await self._resolve_bound_run(
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=thread_id,
            client_run_id=client_run_id,
        )
        return await self._run_service.cancel(tenant_id, run.run_id)

    async def _resolve_bound_run(
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
            binding = await self._bindings.get_by_thread(tenant_id, user_id, thread_id)
            run = await self._run_service.find_by_idempotency_key(
                tenant_id,
                binding.session_id,
                client_run_id,
            )
            if run is None:
                raise NotFoundError(
                    f"AG-UI run is not bound: {thread_id}/{client_run_id}"
                )
            run_id = run.run_id
            async with self._lock:
                self._run_bindings[key] = run_id
        return await self._run_service.get(tenant_id, run_id)

    async def _resolve_binding(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        agent_name: str,
        agent_version: str,
    ) -> AguiThreadBinding:
        async with self._lock:
            try:
                stored = await self._bindings.get_by_thread(tenant_id, user_id, thread_id)
            except NotFoundError:
                stored = None
            if stored is not None:
                session = await self._sessions.get(tenant_id, stored.session_id)
                existing = AguiThreadBinding(
                    session_id=session.session_id,
                    agent_name=session.agent_name,
                    agent_version=session.agent_version,
                )
                if (existing.agent_name, existing.agent_version) != (agent_name, agent_version):
                    raise ConflictError(
                        f"AG-UI thread {thread_id} is already bound to "
                        f"{existing.agent_name}@{existing.agent_version}"
                    )
                if stored.archived_at is not None:
                    await self._bindings.set_archived(
                        tenant_id,
                        user_id,
                        thread_id,
                        archived_at=None,
                    )
                return existing
            session = await self._sessions.create(tenant_id, user_id, agent_name, agent_version)
            binding = AguiThreadBinding(
                session_id=session.session_id,
                agent_name=agent_name,
                agent_version=agent_version,
            )
            timestamp = datetime.now(UTC)
            await self._bindings.add(
                StoredAguiThreadBinding(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    session_id=session.session_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            return binding


def _model_route_override(request: RunAgentInput) -> str | None:
    raw = request.forwarded_props
    if not isinstance(raw, dict):
        return None
    value = raw.get("modelRoute")
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
        raise ConflictError("task model route override is invalid")
    return value


def _latest_user_input(request: RunAgentInput) -> tuple[str, list[str]]:
    for message in reversed(request.messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            return content, []
        text = "\n".join(item.text for item in content if isinstance(item, TextInputContent))
        input_artifact_ids: list[str] = []
        for item in content:
            input_artifact_id: object | None = None
            if isinstance(item, BinaryInputContent):
                input_artifact_id = item.id
            elif isinstance(
                item,
                (
                    ImageInputContent,
                    AudioInputContent,
                    VideoInputContent,
                    DocumentInputContent,
                ),
            ):
                raw_metadata: object = item.metadata
                if isinstance(raw_metadata, dict):
                    metadata = cast(dict[str, object], raw_metadata)
                    input_artifact_id = metadata.get(
                        "inputArtifactId", metadata.get("input_artifact_id")
                    )
                if (
                    input_artifact_id is None
                    and isinstance(item.source, InputContentDataSource)
                    and item.source.value.startswith("input_artifact_")
                ):
                    # @assistant-ui/react-ag-ui converts completed attachments
                    # to typed media data sources based on MIME type. The value
                    # is an opaque server-issued ID, never browser file bytes.
                    input_artifact_id = item.source.value
            if isinstance(input_artifact_id, str) and input_artifact_id:
                input_artifact_ids.append(input_artifact_id)
        return text, input_artifact_ids
    return "", []


def _user_prompts(request: RunAgentInput) -> list[str]:
    prompts: list[str] = []
    for message in request.messages:
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            prompts.append(content)
            continue
        prompts.append(
            "\n".join(item.text for item in content if isinstance(item, TextInputContent))
        )
    return prompts
