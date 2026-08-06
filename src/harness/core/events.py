"""Versioned event facts emitted while a Run executes."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunEvent(BaseModel):
    """An immutable, ordered event within one Run."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    run_id: str
    session_id: str
    tenant_id: str
    sequence: int = Field(ge=1)
    type: str = Field(min_length=1)
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = Field(default=1, ge=1)
    trace_id: str | None = None
    span_id: str | None = None
