"""Request schemas for the public Harness API."""

from pydantic import BaseModel, Field

from harness.core.models import ApprovalStatus


class PublishAgentRequest(BaseModel):
    path: str = Field(min_length=1)


class CreateSessionRequest(BaseModel):
    agent_name: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)


class CreateRunRequest(BaseModel):
    prompt: str = Field(min_length=1)


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalStatus


class PaginationParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class ListRunsParams(PaginationParams):
    session_id: str | None = None
    status: str | None = None
