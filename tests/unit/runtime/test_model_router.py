import pytest

from harness.core.errors import ConflictError
from harness.core.models import ModelCompatibility, ModelRoute
from harness.runtime.model_router import ModelRouter


def route(
    route_id: str,
    provider: str,
    capabilities: frozenset[str],
    compatibility: ModelCompatibility = ModelCompatibility.FULL,
) -> ModelRoute:
    return ModelRoute(
        route_id=route_id,
        provider=provider,
        base_url=f"https://{provider}.example/v1",
        model="claude-sonnet-4-6",
        compatibility=compatibility,
        capabilities=capabilities,
    )


def test_new_api_primary_is_selected_when_capabilities_match() -> None:
    router = ModelRouter(
        [
            route("new-api-default", "new-api", frozenset({"streaming", "tool_use"})),
            route("anthropic-official", "anthropic", frozenset({"streaming"})),
        ]
    )

    result = router.resolve(
        "new-api-default",
        required_capabilities=frozenset({"streaming", "tool_use"}),
        fallback_route_id="anthropic-official",
    )

    assert result.route.route_id == "new-api-default"
    assert result.used_fallback is False
    assert result.event_payload == {
        "route_id": "new-api-default",
        "provider": "new-api",
        "model": "claude-sonnet-4-6",
        "compatibility": "full",
        "capabilities": ["streaming", "tool_use"],
        "used_fallback": False,
    }


def test_explicit_fallback_is_used_for_incompatible_primary() -> None:
    router = ModelRouter(
        [
            route(
                "new-api-default",
                "new-api",
                frozenset({"streaming"}),
                ModelCompatibility.UNSUPPORTED,
            ),
            route(
                "anthropic-official",
                "anthropic",
                frozenset({"streaming", "tool_use"}),
            ),
        ]
    )

    result = router.resolve(
        "new-api-default",
        required_capabilities=frozenset({"tool_use"}),
        fallback_route_id="anthropic-official",
    )

    assert result.route.route_id == "anthropic-official"
    assert result.used_fallback is True


def test_missing_capability_without_explicit_fallback_fails() -> None:
    router = ModelRouter([route("new-api-default", "new-api", frozenset({"streaming"}))])

    with pytest.raises(ConflictError, match="required capabilities"):
        router.resolve(
            "new-api-default",
            required_capabilities=frozenset({"tool_use"}),
        )
