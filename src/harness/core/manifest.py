"""Agent Manifest schema, validation and deterministic snapshotting."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ManifestValidationError(ValueError):
    """Raised when an Agent Manifest cannot be safely published."""


class ManifestModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class AgentMetadata(ManifestModel):
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    version: str = Field(min_length=1)
    labels: dict[str, str] = Field(default_factory=dict)


class ModelSpec(ManifestModel):
    route: str = Field(min_length=1)
    model: str = Field(min_length=1)
    fallback_route: str | None = Field(default=None, alias="fallbackRoute")
    fallback_model: str | None = Field(default=None, alias="fallbackModel")
    required_capabilities: tuple[str, ...] = Field(
        default_factory=tuple, alias="requiredCapabilities"
    )


class PromptSpec(ManifestModel):
    system: str = Field(min_length=1)


class ToolSpec(ManifestModel):
    builtin: str | None = None
    python_entry: str | None = Field(default=None, alias="python")
    mcp: str | None = None

    @model_validator(mode="after")
    def exactly_one_tool_source(self) -> ToolSpec:
        values = (self.builtin, self.python_entry, self.mcp)
        if sum(value is not None for value in values) != 1:
            raise ValueError("tool must declare exactly one of builtin, python, or mcp")
        return self


class SubagentSpec(ManifestModel):
    ref: str = Field(min_length=1)


class HookSpec(ManifestModel):
    python_entry: str = Field(alias="python", min_length=1)


class PermissionSpec(ManifestModel):
    policy: str = Field(min_length=1)


class WorkspaceSpec(ManifestModel):
    mode: Literal["isolated"] = "isolated"
    restore_session: bool = Field(default=True, alias="restoreSession")
    archive_on_complete: bool = Field(default=True, alias="archiveOnComplete")


class LimitSpec(ManifestModel):
    max_turns: int = Field(default=30, alias="maxTurns", ge=1)
    timeout_seconds: int = Field(default=1800, alias="timeoutSeconds", ge=1)
    max_budget_usd: float | None = Field(default=None, alias="maxBudgetUsd", gt=0)


class AgentSpec(ManifestModel):
    runtime: Literal["claude-agent-sdk"]
    model: ModelSpec
    prompt: PromptSpec
    skills: tuple[str, ...] = ()
    tools: tuple[ToolSpec, ...] = ()
    subagents: tuple[SubagentSpec, ...] = ()
    hooks: tuple[HookSpec, ...] = ()
    permissions: PermissionSpec
    workspace: WorkspaceSpec = WorkspaceSpec()
    limits: LimitSpec = LimitSpec()


class AgentManifest(ManifestModel):
    api_version: Literal["harness/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["Agent"]
    metadata: AgentMetadata
    spec: AgentSpec


class AgentManifestSnapshot(ManifestModel):
    manifest: AgentManifest
    system_prompt: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


_SECRET_KEY = re.compile(r"(?:api[_-]?key|token|password|secret)", re.IGNORECASE)


def _assert_no_inline_secrets(value: object, path: str = "manifest") -> None:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        for key, child in mapping.items():
            key_text = str(key)
            if _SECRET_KEY.search(key_text) and child not in (None, ""):
                raise ManifestValidationError(
                    f"secret-like field is not allowed: {path}.{key_text}"
                )
            _assert_no_inline_secrets(child, f"{path}.{key_text}")
    elif isinstance(value, list):
        sequence = cast(list[object], value)
        for index, child in enumerate(sequence):
            _assert_no_inline_secrets(child, f"{path}[{index}]")


def _resolve_file(root: Path, relative: str, label: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ManifestValidationError(f"{label} must stay inside the Agent directory")
    if not candidate.is_file():
        raise ManifestValidationError(f"{label} file does not exist: {relative}")
    return candidate


def _hash_skill_path(digest: Any, root: Path, relative: str) -> None:
    skill_path = (root / relative).resolve()
    if not skill_path.is_relative_to(root) or not skill_path.exists():
        raise ManifestValidationError(f"skill path does not exist: {relative}")
    paths = (
        [skill_path]
        if skill_path.is_file()
        else sorted(path for path in skill_path.rglob("*") if path.is_file())
    )
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())


def load_manifest(
    path: str | Path,
    *,
    environment: Literal["local", "test", "production"] = "local",
) -> AgentManifestSnapshot:
    """Load, validate, resolve and hash one Agent Manifest."""

    manifest_path = Path(path).resolve()
    try:
        raw_value = yaml.safe_load(manifest_path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ManifestValidationError(f"cannot read manifest: {error}") from error
    if not isinstance(raw_value, dict):
        raise ManifestValidationError("manifest must be a YAML object")

    raw = cast(dict[str, Any], raw_value)
    _assert_no_inline_secrets(raw)
    try:
        manifest = AgentManifest.model_validate(raw)
    except ValidationError as error:
        raise ManifestValidationError(str(error)) from error

    if environment == "production":
        for subagent in manifest.spec.subagents:
            if subagent.ref.endswith("@latest") or "@" not in subagent.ref:
                raise ManifestValidationError(
                    "production subagent references require an explicit version, "
                    f"not latest: {subagent.ref}"
                )

    root = manifest_path.parent.resolve()
    prompt_path = _resolve_file(root, manifest.spec.prompt.system, "system prompt")
    system_prompt = prompt_path.read_text()

    digest = hashlib.sha256()
    canonical = json.dumps(
        manifest.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    digest.update(canonical.encode())
    digest.update(prompt_path.relative_to(root).as_posix().encode())
    digest.update(system_prompt.encode())
    for skill in sorted(manifest.spec.skills):
        _hash_skill_path(digest, root, skill)

    return AgentManifestSnapshot(
        manifest=manifest,
        system_prompt=system_prompt,
        content_hash=digest.hexdigest(),
    )
