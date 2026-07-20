"""Request schemas for the public Harness API."""

from typing import Any, cast

from pydantic import BaseModel, Field, model_validator

from harness.core.models import AgentVersion, ApprovalStatus


class PublishAgentRequest(BaseModel):
    path: str = Field(min_length=1)


class AgentCatalogItem(BaseModel):
    name: str
    version: str
    display_name: str
    domain: str
    model_route: str | None = None
    model: str | None = None
    model_capabilities: tuple[str, ...] = ()

    @classmethod
    def from_version(cls, version: AgentVersion) -> "AgentCatalogItem":
        manifest = version.snapshot.get("manifest")
        metadata = (
            cast(dict[str, Any], manifest).get("metadata") if isinstance(manifest, dict) else None
        )
        labels = (
            cast(dict[str, Any], metadata).get("labels") if isinstance(metadata, dict) else None
        )
        label_values = cast(dict[str, Any], labels) if isinstance(labels, dict) else {}
        spec = cast(dict[str, Any], manifest).get("spec") if isinstance(manifest, dict) else None
        model_spec = cast(dict[str, Any], spec).get("model") if isinstance(spec, dict) else None
        model_values = cast(dict[str, Any], model_spec) if isinstance(model_spec, dict) else {}
        raw_capabilities = model_values.get("requiredCapabilities")
        capabilities = (
            tuple(str(value) for value in raw_capabilities)
            if isinstance(raw_capabilities, list)
            else ()
        )
        return cls(
            name=version.name,
            version=version.version,
            display_name=str(label_values.get("display-name") or version.name),
            domain=str(label_values.get("domain") or "default"),
            model_route=(str(model_values["route"]) if model_values.get("route") else None),
            model=str(model_values["model"]) if model_values.get("model") else None,
            model_capabilities=capabilities,
        )


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
