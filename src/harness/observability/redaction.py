"""Conservative recursive redaction before telemetry export."""

import hashlib
import json
import re
from typing import Any, cast

_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "file.content",
    "file_content",
    "input.content",
    "input_content",
    "memory",
    "password",
    "prompt",
    "secret",
    "token",
)

_SAFE_NUMERIC_METRICS = frozenset(
    {
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "harness.usage.cache_creation_input_tokens",
        "harness.usage.cache_read_input_tokens",
    }
)

_AUTHORIZATION_TEXT = re.compile(r"(?i)\b(authorization\s*[:=]\s*)([^'\"\n]+)")
_BEARER_TEXT = re.compile(r"(?i)\b(bearer\s+)([^\s'\"&]+)")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(token|api[_-]?key|secret|password)(\s*[:=]\s*)([^\s'\"&]+)"
)


def _is_safe_numeric_metric(key: object, value: object) -> bool:
    return (
        str(key).lower() in _SAFE_NUMERIC_METRICS
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= 0
    )


def correlation_hash(value: str) -> str:
    """Return a stable, non-reversible short identity correlation value."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def redact_content(value: object, *, limit: int) -> str:
    """Return bounded debug content with common credential forms removed."""

    if isinstance(value, str):
        serialized = value
    else:
        serialized = json.dumps(
            redact(value),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    sanitized = _AUTHORIZATION_TEXT.sub(r"\1[REDACTED]", serialized)
    sanitized = _BEARER_TEXT.sub(r"\1[REDACTED]", sanitized)
    sanitized = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", sanitized)
    return sanitized if len(sanitized) <= limit else f"{sanitized[: limit - 1]}…"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        mapping = cast(dict[object, Any], value)
        return {
            str(key): (
                child
                if _is_safe_numeric_metric(key, child)
                else "[REDACTED]"
                if any(marker in str(key).lower() for marker in _SENSITIVE_MARKERS)
                else redact(child)
            )
            for key, child in mapping.items()
        }
    if isinstance(value, list):
        sequence = cast(list[Any], value)
        return [redact(child) for child in sequence]
    if isinstance(value, tuple):
        sequence = cast(tuple[Any, ...], value)
        return tuple(redact(child) for child in sequence)
    return value
