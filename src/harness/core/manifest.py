"""Agent Manifest schema, validation and deterministic snapshotting."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
from collections.abc import Sequence
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
    alias: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9-]*$",
    )
    description: str | None = Field(default=None, min_length=1, max_length=500)
    background: bool = False

    @property
    def runtime_name(self) -> str:
        package_name, separator, _version = self.ref.rpartition("@")
        return self.alias or (package_name if separator else self.ref)


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

    @model_validator(mode="after")
    def unique_subagent_runtime_names(self) -> AgentSpec:
        runtime_names = [subagent.runtime_name for subagent in self.subagents]
        duplicates = sorted(
            {name for name in runtime_names if runtime_names.count(name) > 1}
        )
        if duplicates:
            raise ValueError(
                "duplicate subagent runtime name: " + ", ".join(duplicates)
            )
        return self


class AgentManifest(ManifestModel):
    api_version: Literal["harness/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["Agent"]
    metadata: AgentMetadata
    spec: AgentSpec


class SkillFileSnapshot(ManifestModel):
    path: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)


class SkillSnapshot(ManifestModel):
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    description: str = Field(min_length=1)
    source: str = Field(min_length=1)
    files: tuple[SkillFileSnapshot, ...] = ()
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class AgentManifestSnapshot(ManifestModel):
    manifest: AgentManifest
    system_prompt: str
    skill_snapshots: tuple[SkillSnapshot, ...] = ()
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


_SECRET_KEY = re.compile(r"(?:api[_-]?key|token|password|secret)", re.IGNORECASE)
_MAX_SKILL_FILE_BYTES = 2 * 1024 * 1024
_MAX_SKILL_TOTAL_BYTES = 10 * 1024 * 1024


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


def _parse_skill_frontmatter(path: Path) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ManifestValidationError(f"cannot read Skill frontmatter: {error}") from error
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ManifestValidationError("SKILL.md must start with YAML frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as error:
        raise ManifestValidationError("SKILL.md frontmatter is not closed") from error
    try:
        raw = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as error:
        raise ManifestValidationError(f"invalid SKILL.md frontmatter: {error}") from error
    if not isinstance(raw, dict):
        raise ManifestValidationError("SKILL.md frontmatter must be a YAML object")
    frontmatter = cast(dict[str, object], raw)
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9-]*", name) is None:
        raise ManifestValidationError("Skill name must be lowercase kebab-case")
    if not isinstance(description, str) or not description.strip():
        raise ManifestValidationError("Skill description must be a non-empty string")
    return name, description.strip()


def _snapshot_skill(root: Path, relative: str) -> SkillSnapshot:
    skill_path = (root / relative).resolve()
    if not skill_path.is_relative_to(root) or not skill_path.exists():
        raise ManifestValidationError(f"skill path does not exist: {relative}")
    if not skill_path.is_dir():
        raise ManifestValidationError(f"skill path must be a directory: {relative}")
    source_path = root / relative
    if source_path.is_symlink():
        raise ManifestValidationError(f"Skill path cannot be a symlink: {relative}")
    paths = sorted(path for path in skill_path.rglob("*") if path.is_file() or path.is_symlink())
    if not paths:
        raise ManifestValidationError(f"Skill directory is empty: {relative}")
    for path in paths:
        if path.is_symlink():
            raise ManifestValidationError(
                f"Skill files cannot be symlinks: {path.relative_to(skill_path).as_posix()}"
            )
        if not path.is_file():
            raise ManifestValidationError(
                f"Skill contains an unsupported file: {path.relative_to(skill_path).as_posix()}"
            )
    skill_md = skill_path / "SKILL.md"
    if not skill_md.is_file():
        raise ManifestValidationError(f"Skill directory must contain SKILL.md: {relative}")
    name, description = _parse_skill_frontmatter(skill_md)
    if skill_path.name != name:
        raise ManifestValidationError(
            f"Skill directory name must match frontmatter name: {skill_path.name} != {name}"
        )
    skill_digest = hashlib.sha256()
    snapshots: list[SkillFileSnapshot] = []
    total_bytes = 0
    for path in paths:
        content = path.read_bytes()
        if len(content) > _MAX_SKILL_FILE_BYTES:
            raise ManifestValidationError(
                f"Skill file exceeds {_MAX_SKILL_FILE_BYTES} bytes: "
                f"{path.relative_to(skill_path).as_posix()}"
            )
        total_bytes += len(content)
        if total_bytes > _MAX_SKILL_TOTAL_BYTES:
            raise ManifestValidationError(
                f"Skill exceeds {_MAX_SKILL_TOTAL_BYTES} total bytes: {relative}"
            )
        relative_file = path.relative_to(skill_path).as_posix()
        file_hash = hashlib.sha256(content).hexdigest()
        skill_digest.update(relative_file.encode())
        skill_digest.update(content)
        snapshots.append(
            SkillFileSnapshot(
                path=relative_file,
                content_base64=base64.b64encode(content).decode("ascii"),
                sha256=file_hash,
                size_bytes=len(content),
            )
        )
    return SkillSnapshot(
        name=name,
        description=description,
        source=relative,
        files=tuple(snapshots),
        content_hash=skill_digest.hexdigest(),
    )


def materialize_skill_snapshots(
    snapshot: AgentManifestSnapshot, workspace: str | Path
) -> tuple[str, ...]:
    """Materialize immutable Skills using the layout discovered by Claude Agent SDK."""

    return materialize_skill_snapshot_set((snapshot,), workspace)


def materialize_skill_snapshot_set(
    snapshots: Sequence[AgentManifestSnapshot], workspace: str | Path
) -> tuple[str, ...]:
    """Materialize main/subagent Skills once, rejecting conflicting names."""

    skills_root = Path(workspace).resolve() / ".claude" / "skills"
    if skills_root.exists():
        if skills_root.is_symlink():
            raise ManifestValidationError("workspace Skill root cannot be a symlink")
        shutil.rmtree(skills_root)
    skills_root.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    skills_by_name: dict[str, SkillSnapshot] = {}
    for snapshot in snapshots:
        for skill in snapshot.skill_snapshots:
            existing = skills_by_name.get(skill.name)
            if existing is not None and existing.content_hash != skill.content_hash:
                raise ManifestValidationError(
                    f"conflicting immutable Skill name: {skill.name}"
                )
            skills_by_name[skill.name] = skill
    for skill in sorted(skills_by_name.values(), key=lambda item: item.name):
        target_root = (skills_root / skill.name).resolve()
        if not target_root.is_relative_to(skills_root):
            raise ManifestValidationError(f"unsafe Skill name: {skill.name}")
        for file in skill.files:
            target = (target_root / file.path).resolve()
            if not target.is_relative_to(target_root):
                raise ManifestValidationError(f"unsafe Skill snapshot path: {file.path}")
            try:
                content = base64.b64decode(file.content_base64, validate=True)
            except ValueError as error:
                raise ManifestValidationError(
                    f"invalid base64 Skill snapshot: {skill.name}/{file.path}"
                ) from error
            if (
                len(content) != file.size_bytes
                or hashlib.sha256(content).hexdigest() != file.sha256
            ):
                raise ManifestValidationError(
                    f"corrupt Skill snapshot: {skill.name}/{file.path}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        names.append(skill.name)
    return tuple(names)


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
    skill_snapshots = tuple(
        _snapshot_skill(root, skill) for skill in sorted(manifest.spec.skills)
    )
    skill_names = [skill.name for skill in skill_snapshots]
    duplicate_names = sorted({name for name in skill_names if skill_names.count(name) > 1})
    if duplicate_names:
        raise ManifestValidationError(
            f"duplicate Skill name: {', '.join(duplicate_names)}"
        )
    for skill in skill_snapshots:
        digest.update(skill.source.encode())
        digest.update(skill.content_hash.encode())

    return AgentManifestSnapshot(
        manifest=manifest,
        system_prompt=system_prompt,
        skill_snapshots=skill_snapshots,
        content_hash=digest.hexdigest(),
    )
