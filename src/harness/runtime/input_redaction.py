"""Shared redaction rules for browser-uploaded workspace inputs."""

from pathlib import Path
from typing import Any, cast

INPUT_CONTENT_REDACTION = "[Input file content omitted from durable events]"
STAGED_INPUT_READ_MARKER = "staged_input_read"


def staged_input_paths(workspace: Path, input_files: tuple[str, ...]) -> dict[Path, str]:
    return {
        (workspace / relative_path).resolve(): relative_path
        for relative_path in input_files
    }


def staged_read_path(
    payload: dict[str, Any],
    *,
    workspace: Path,
    staged_paths: dict[Path, str],
) -> str | None:
    """Return the safe relative path when a Read targets a staged input exactly."""
    if str(payload.get("name", "")).casefold() != "read":
        return None
    arguments = payload.get("arguments")
    if not isinstance(arguments, dict):
        return None
    typed_arguments = cast(dict[str, Any], arguments)
    raw_path = typed_arguments.get("file_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        return staged_paths.get(candidate.resolve())
    except (OSError, RuntimeError):
        return None


def redact_workspace_paths(value: Any, workspace: Path) -> Any:
    """Replace ephemeral sandbox roots without changing the event shape."""
    workspace_path = str(workspace.resolve())
    if isinstance(value, str):
        return value.replace(workspace_path, "/workspace")
    if isinstance(value, list):
        return [
            redact_workspace_paths(item, workspace)
            for item in cast(list[Any], value)
        ]
    if isinstance(value, dict):
        return {
            key: redact_workspace_paths(item, workspace)
            for key, item in cast(dict[str, Any], value).items()
        }
    return value
