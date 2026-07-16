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
    input_artifact_ids: tuple[str, ...] = Field(default=())


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalStatus
