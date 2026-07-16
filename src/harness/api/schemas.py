"""Request schemas for the public Harness API."""

from pydantic import BaseModel, Field, model_validator

from harness.core.models import ApprovalStatus


class PublishAgentRequest(BaseModel):
    path: str = Field(min_length=1)


class CreateSessionRequest(BaseModel):
    agent_name: str = Field(min_length=1)
    agent_version: str | None = Field(default=None, min_length=1)
    environment: str | None = Field(default=None, pattern="^(test|canary|production)$")

    @model_validator(mode="after")
    def select_version_or_environment(self) -> "CreateSessionRequest":
        if (self.agent_version is None) == (self.environment is None):
            raise ValueError("provide exactly one of agent_version or environment")
        return self


class CreateRunRequest(BaseModel):
    prompt: str = Field(min_length=1)
    input_artifact_ids: tuple[str, ...] = Field(default=())


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalStatus
