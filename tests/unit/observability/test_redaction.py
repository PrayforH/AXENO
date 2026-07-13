from harness.observability.redaction import correlation_hash, redact


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


def test_redacts_memory_and_file_content_keys() -> None:
    assert redact(
        {
            "memory.content": "remember this",
            "file_content": "document body",
            "item.count": 2,
        }
    ) == {
        "memory.content": "[REDACTED]",
        "file_content": "[REDACTED]",
        "item.count": 2,
    }


def test_correlation_hash_is_stable_and_does_not_expose_identity() -> None:
    first = correlation_hash("tenant-a")

    assert first == correlation_hash("tenant-a")
    assert first != correlation_hash("tenant-b")
    assert "tenant-a" not in first
    assert len(first) == 16
