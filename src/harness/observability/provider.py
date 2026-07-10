"""OpenTelemetry provider composition and distributed context helpers."""

from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager

from opentelemetry import propagate
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import NoOpTracerProvider, Tracer

from harness.config import Settings

ProcessorFactory = Callable[[SpanExporter], SpanProcessor]


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

    def inject(self) -> dict[str, str]:
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        return carrier

    @contextmanager
    def span(
        self,
        name: str,
        *,
        carrier: Mapping[str, str] | None = None,
        attributes: Mapping[str, str | bool | int | float] | None = None,
    ) -> Generator[None]:
        context = propagate.extract(dict(carrier)) if carrier else None
        with self.tracer.start_as_current_span(
            name, context=context, attributes=dict(attributes or {})
        ):
            yield


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
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    provider.add_span_processor(processor_factory(selected_exporter))
    return Observability(
        enabled=True,
        tracer=provider.get_tracer("harness"),
        exporter=selected_exporter,
    )
