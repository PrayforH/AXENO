"""Safe SDK diagnostics that never forward environment values."""


def redact_sdk_stderr(line: str) -> str:
    lowered = line.lower()
    if any(marker in lowered for marker in ("api_key", "auth_token", "authorization")):
        return "[redacted sdk diagnostic]"
    return line


def discard_sdk_stderr(line: str) -> None:
    """Sanitize diagnostics at the boundary; logging is opt-in elsewhere."""

    redact_sdk_stderr(line)
