from harness.runtime.audit_redaction import redact_tool_arguments


def test_redacts_credentials_and_write_content_from_audit_copy() -> None:
    original = {
        "file_path": "outputs/result.md",
        "content": "private report",
        "headers": {"Authorization": "Bearer private-token"},
    }

    redacted = redact_tool_arguments("Write", original)

    assert redacted == {
        "file_path": "outputs/result.md",
        "content": "[REDACTED]",
        "headers": "[REDACTED]",
    }
    assert original["content"] == "private report"


def test_redacts_inline_authorization_from_bash_command() -> None:
    redacted = redact_tool_arguments(
        "Bash",
        {"command": "curl -H 'Authorization: Bearer private-command-token' /status"},
    )

    assert "private-command-token" not in redacted["command"]
    assert "[REDACTED]" in redacted["command"]
