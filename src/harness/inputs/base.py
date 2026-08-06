"""Framework-independent input processing contract."""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from harness.core.models import ProcessingStatus


class DerivedInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    relative_path: str
    media_type: str
    content: bytes
    metadata: dict[str, Any] = Field(default_factory=dict)


class InputProcessingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ProcessingStatus
    processor: str
    derived: tuple[DerivedInput, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None


class InputProcessor(Protocol):
    def process(
        self, *, name: str, media_type: str, content: bytes
    ) -> InputProcessingResult: ...

