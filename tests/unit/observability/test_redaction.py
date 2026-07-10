from harness.observability.redaction import redact


def test_redacts_secrets_and_prompt_content_recursively() -> None:
    value = {
        "api_key": "secret",
        "prompt": "private request",
        "safe": "visible",
        "nested": {"Authorization": "Bearer token", "count": 2},
    }

    assert redact(value) == {
        "api_key": "[REDACTED]",
        "prompt": "[REDACTED]",
        "safe": "visible",
        "nested": {"Authorization": "[REDACTED]", "count": 2},
    }
