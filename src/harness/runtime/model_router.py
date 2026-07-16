"""Explicit capability-aware model gateway routing."""

from pydantic import BaseModel, ConfigDict

from harness.core.errors import ConflictError, NotFoundError
from harness.core.models import ModelCompatibility, ModelRoute


class RoutingDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    route: ModelRoute
    used_fallback: bool

    @property
    def event_payload(self) -> dict[str, object]:
        return {
            "route_id": self.route.route_id,
            "provider": self.route.provider,
            "model": self.route.model,
            "compatibility": self.route.compatibility.value,
            "capabilities": sorted(self.route.capabilities),
            "used_fallback": self.used_fallback,
        }


class ModelRouter:
    def __init__(self, routes: list[ModelRoute]) -> None:
        self._routes = {route.route_id: route for route in routes}

    def _get(self, route_id: str) -> ModelRoute:
        try:
            return self._routes[route_id]
        except KeyError as error:
            raise NotFoundError(f"model route not found: {route_id}") from error

    @staticmethod
    def _supports(route: ModelRoute, required: frozenset[str]) -> bool:
        return route.compatibility is not ModelCompatibility.UNSUPPORTED and required.issubset(
            route.capabilities
        )

    def resolve(
        self,
        primary_route_id: str,
        *,
        required_capabilities: frozenset[str] = frozenset(),
        fallback_route_id: str | None = None,
    ) -> RoutingDecision:
        primary = self._get(primary_route_id)
        if self._supports(primary, required_capabilities):
            return RoutingDecision(route=primary, used_fallback=False)
        if fallback_route_id is not None:
            fallback = self._routes.get(fallback_route_id)
            if fallback is None:
                raise ConflictError(
                    "model route does not satisfy required capabilities and "
                    f"fallback route is not configured: {fallback_route_id}"
                )
            if self._supports(fallback, required_capabilities):
                return RoutingDecision(route=fallback, used_fallback=True)
        missing = sorted(required_capabilities - primary.capabilities)
        raise ConflictError(
            "model route does not satisfy required capabilities: "
            f"{primary.route_id} missing={missing} compatibility={primary.compatibility.value}"
        )
