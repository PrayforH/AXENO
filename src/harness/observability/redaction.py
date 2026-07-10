"""Conservative recursive redaction before telemetry export."""

from typing import Any, cast

_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "password",
    "prompt",
    "secret",
    "token",
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        mapping = cast(dict[object, Any], value)
        return {
            str(key): (
                "[REDACTED]"
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
