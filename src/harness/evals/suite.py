"""Load and validate deterministic Agent evaluation suites."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class EvalSuiteValidationError(ValueError):
    """Raised when an evaluation suite cannot be used safely."""


class EvalModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class EvalExpectation(EvalModel):
    terminal_statuses: tuple[str, ...] = Field(
        default=("succeeded",), alias="terminalStatuses"
    )
    required_tools: tuple[str, ...] = Field(default=(), alias="requiredTools")
    forbidden_tools: tuple[str, ...] = Field(default=(), alias="forbiddenTools")
    output_contains: tuple[str, ...] = Field(default=(), alias="outputContains")
    approval_required: bool = Field(default=False, alias="approvalRequired")
    max_duration_seconds: float = Field(default=120, alias="maxDurationSeconds", gt=0)

    @model_validator(mode="after")
    def disjoint_tools(self) -> EvalExpectation:
        overlap = sorted(set(self.required_tools) & set(self.forbidden_tools))
        if overlap:
            raise ValueError(
                f"tools cannot be both required and forbidden: {', '.join(overlap)}"
            )
        return self


class EvalInputFile(EvalModel):
    path: str = Field(min_length=1)
    media_type: str = Field(
        default="application/octet-stream", alias="mediaType", min_length=1
    )

    @model_validator(mode="after")
    def safe_relative_path(self) -> EvalInputFile:
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or "\\" in self.path
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("evaluation input path must be a safe relative path")
        return self


class EvalCase(EvalModel):
    id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    tags: tuple[str, ...] = Field(min_length=1)
    prompt: str = Field(min_length=1)
    input_files: tuple[EvalInputFile, ...] = Field(
        default=(), alias="inputFiles"
    )
    expect: EvalExpectation = EvalExpectation()


class EvalSuite(EvalModel):
    api_version: Literal["harness/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["EvalSuite"]
    agent: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    cases: tuple[EvalCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_case_ids(self) -> EvalSuite:
        ids = [case.id for case in self.cases]
        duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate evaluation case: {', '.join(duplicates)}")
        return self


def load_eval_suite(
    path: str | Path, *, expected_agent: str | None = None
) -> EvalSuite:
    suite_path = Path(path)
    try:
        raw_value = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise EvalSuiteValidationError(f"cannot read evaluation suite: {error}") from error
    if not isinstance(raw_value, dict):
        raise EvalSuiteValidationError("evaluation suite must be a YAML object")
    try:
        suite = EvalSuite.model_validate(cast(dict[str, Any], raw_value))
    except ValidationError as error:
        message = str(error)
        if "duplicate evaluation case" in message:
            duplicate = message.split("duplicate evaluation case", 1)[1].split("\n", 1)[0]
            raise EvalSuiteValidationError(
                f"duplicate evaluation case{duplicate}"
            ) from error
        raise EvalSuiteValidationError(message) from error
    if expected_agent is not None and suite.agent != expected_agent:
        raise EvalSuiteValidationError(
            f"evaluation suite targets {suite.agent}, expected {expected_agent}"
        )
    return suite
