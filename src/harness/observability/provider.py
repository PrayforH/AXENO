"""OpenTelemetry provider composition and distributed context helpers."""

from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import cast

from opentelemetry import propagate
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import (
    NoOpTracerProvider,
    Status,
    StatusCode,
    Tracer,
    get_current_span,
)

from harness.config import Settings
from harness.observability.redaction import redact

ProcessorFactory = Callable[[SpanExporter], SpanProcessor]
AttributeValue = str | bool | int | float


def _safe_attributes(
    attributes: Mapping[str, AttributeValue] | None,
) -> dict[str, AttributeValue]:
    return cast(
        dict[str, AttributeValue],
        redact(dict(attributes or {})),
    )


class Observability:
    def __init__(
        self,
        *,
        enabled: bool,
        tracer: Tracer,
        exporter: SpanExporter | None,
    ) -> None:
        self.enabled = enabled
        self.tracer = tracer
        self.exporter = exporter
        self._bound_attributes: ContextVar[dict[str, AttributeValue] | None] = ContextVar(
            f"harness_observability_attributes_{id(self)}",
            default=None,
        )

    def inject(self) -> dict[str, str]:
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        return carrier

    @contextmanager
    def bind_attributes(
        self,
        attributes: Mapping[str, AttributeValue],
    ) -> Generator[None]:
        inherited = self._bound_attributes.get() or {}
        token = self._bound_attributes.set(
            {**inherited, **_safe_attributes(attributes)}
        )
        try:
            yield
        finally:
            self._bound_attributes.reset(token)

    def annotate_current_span(
        self,
        attributes: Mapping[str, AttributeValue],
    ) -> None:
        span = get_current_span()
        for key, value in _safe_attributes(attributes).items():
            span.set_attribute(key, value)

    def mark_current_span_error(self, error_type: str) -> None:
        safe_type = str(redact(error_type))
        span = get_current_span()
        span.add_event("error", {"error.type": safe_type})
        span.set_status(Status(StatusCode.ERROR, safe_type))

    @contextmanager
    def span(
        self,
        name: str,
        *,
        carrier: Mapping[str, str] | None = None,
        attributes: Mapping[str, AttributeValue] | None = None,
    ) -> Generator[None]:
        context = propagate.extract(dict(carrier)) if carrier else None
        safe_attributes = {
            **(self._bound_attributes.get() or {}),
            **_safe_attributes(attributes),
        }
        with self.tracer.start_as_current_span(
            name,
            context=context,
            attributes=safe_attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield
            except BaseException as error:
                error_type = type(error).__name__
                span.add_event("exception", {"exception.type": error_type})
                span.set_status(Status(StatusCode.ERROR, error_type))
                raise


def _parse_headers(value: str) -> dict[str, str]:
    pairs = (part.strip() for part in value.split(","))
    return {
        key.strip(): child.strip()
        for part in pairs
        if part and "=" in part
        for key, child in [part.split("=", 1)]
    }


def build_observability(
    settings: Settings,
    *,
    exporter: SpanExporter | None = None,
    processor_factory: ProcessorFactory = BatchSpanProcessor,
) -> Observability:
    if not settings.otel_enabled:
        provider = NoOpTracerProvider()
        return Observability(
            enabled=False,
            tracer=provider.get_tracer("harness"),
            exporter=None,
        )
    selected_exporter = exporter
    if selected_exporter is None:
        if not settings.otlp_endpoint:
            raise ValueError("HARNESS_OTLP_ENDPOINT is required when OTEL is enabled")
        selected_exporter = OTLPSpanExporter(
            endpoint=settings.otlp_endpoint,
            headers=_parse_headers(settings.otlp_headers.get_secret_value()),
        )
    resource_attributes = {"service.name": settings.otel_service_name}
    if settings.otel_environment:
        resource_attributes["deployment.environment.name"] = settings.otel_environment
    provider = TracerProvider(resource=Resource.create(resource_attributes))
    provider.add_span_processor(processor_factory(selected_exporter))
    return Observability(
        enabled=True,
        tracer=provider.get_tracer("harness"),
        exporter=selected_exporter,
    )
