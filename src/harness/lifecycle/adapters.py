from __future__ import annotations

from typing import Protocol

from harness.lifecycle.models import DataLifecycleJob


class LifecycleAdapter(Protocol):
    @property
    def name(self) -> str: ...

    async def export(self, job: DataLifecycleJob) -> tuple[object, int]: ...

    async def delete(self, job: DataLifecycleJob) -> int: ...


class EmptyLifecycleAdapter:
    """Explicit adapter for a configured external system with no matching data."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def export(self, job: DataLifecycleJob) -> tuple[object, int]:
        del job
        return {}, 0

    async def delete(self, job: DataLifecycleJob) -> int:
        del job
        return 0
