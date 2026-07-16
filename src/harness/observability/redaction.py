"""Conservative recursive redaction before telemetry export."""

import hashlib
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
