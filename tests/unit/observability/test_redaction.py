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


def test_allows_only_known_non_negative_numeric_token_metrics() -> None:
    assert redact(
        {
            "gen_ai.usage.input_tokens": 12,
            "gen_ai.usage.output_tokens": 4,
            "harness.usage.cache_read_input_tokens": 3,
            "harness.usage.cache_creation_input_tokens": 2,
            "gen_ai.usage.input_tokens.secret": 99,
            "access_token": "never-show",
        }
    ) == {
        "gen_ai.usage.input_tokens": 12,
        "gen_ai.usage.output_tokens": 4,
        "harness.usage.cache_read_input_tokens": 3,
        "harness.usage.cache_creation_input_tokens": 2,
        "gen_ai.usage.input_tokens.secret": "[REDACTED]",
        "access_token": "[REDACTED]",
    }
    assert redact({"gen_ai.usage.input_tokens": "secret"}) == {
        "gen_ai.usage.input_tokens": "[REDACTED]"
    }


def test_correlation_hash_is_stable_and_does_not_expose_identity() -> None:
    first = correlation_hash("tenant-a")

    assert first == correlation_hash("tenant-a")
    assert first != correlation_hash("tenant-b")
    assert "tenant-a" not in first
    assert len(first) == 16
