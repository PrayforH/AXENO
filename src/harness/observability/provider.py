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
    Span,
    Status,
    StatusCode,
    Tracer,
    get_current_span,
)

from harness.config import Settings
from harness.observability.redaction import redact, redact_content

ProcessorFactory = Callable[[SpanExporter], SpanProcessor]
AttributeValue = str | bool | int | float
_ATTRIBUTE_PREFIX_ALLOWLIST = (
    "agent.",
    "deployment.",
    "eval.",
    "gen_ai.",
    "harness.",
    "http.",
    "langfuse.",
    "run.",
    "session.",
    "tenant.",
)
_ATTRIBUTE_KEY_ALLOWLIST = frozenset({"input.count", "item.count"})


def _safe_attributes(
    attributes: Mapping[str, AttributeValue] | None,
) -> dict[str, AttributeValue]:
    sanitized = cast(dict[str, AttributeValue], redact(dict(attributes or {})))
    return {
        key: value
        for key, value in sanitized.items()
        if key in _ATTRIBUTE_KEY_ALLOWLIST
        or key.startswith(_ATTRIBUTE_PREFIX_ALLOWLIST)
        or value == "[REDACTED]"
    }


class Observability:
    def __init__(
        self,
        *,
        enabled: bool,
        tracer: Tracer,
        exporter: SpanExporter | None,
        content_capture: str = "off",
        content_max_chars: int = 12_000,
    ) -> None:
        self.enabled = enabled
        self.tracer = tracer
        self.exporter = exporter
        self.content_capture = content_capture
        self.content_max_chars = content_max_chars
        self._bound_attributes: ContextVar[dict[str, AttributeValue] | None] = ContextVar(
            f"harness_observability_attributes_{id(self)}",
            default=None,
        )

    def inject(self) -> dict[str, str]:
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        return carrier

    def current_trace_id(self) -> str | None:
        context = get_current_span().get_span_context()
        return f"{context.trace_id:032x}" if context.is_valid else None

    def current_span_id(self) -> str | None:
        context = get_current_span().get_span_context()
        return f"{context.span_id:016x}" if context.is_valid else None

    @contextmanager
    def bind_attributes(
        self,
        attributes: Mapping[str, AttributeValue],
    ) -> Generator[None]:
        inherited = self._bound_attributes.get() or {}
        token = self._bound_attributes.set({**inherited, **_safe_attributes(attributes)})
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

    @property
    def captures_content(self) -> bool:
        return self.enabled and self.content_capture == "redacted"

    def annotate_current_io(
        self,
        *,
        input_value: object | None = None,
        output_value: object | None = None,
        trace_level: bool = False,
    ) -> None:
        if not self.captures_content:
            return
        self._annotate_span_io(
            get_current_span(),
            input_value=input_value,
            output_value=output_value,
            trace_level=trace_level,
        )

    def _annotate_span_io(
        self,
        span: Span,
        *,
        input_value: object | None,
        output_value: object | None,
        trace_level: bool,
    ) -> None:
        # Langfuse v4 uses the root observation as the authoritative trace
        # input/output. Keep the deprecated trace fields as a compatibility
        # copy for existing trace-level evaluators during the migration.
        prefixes = (
            ("langfuse.observation", "langfuse.trace")
            if trace_level
            else ("langfuse.observation",)
        )
        if input_value is not None:
            value = redact_content(input_value, limit=self.content_max_chars)
            for prefix in prefixes:
                span.set_attribute(f"{prefix}.input", value)
        if output_value is not None:
            value = redact_content(output_value, limit=self.content_max_chars)
            for prefix in prefixes:
                span.set_attribute(f"{prefix}.output", value)

    def record_completed_span(
        self,
        name: str,
        *,
        started_at_ns: int,
        ended_at_ns: int,
        attributes: Mapping[str, AttributeValue] | None = None,
        input_value: object | None = None,
        output_value: object | None = None,
        error_type: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        safe_attributes = {
            **(self._bound_attributes.get() or {}),
            **_safe_attributes(attributes),
        }
        span = self.tracer.start_span(
            name,
            attributes=safe_attributes,
            start_time=started_at_ns,
            record_exception=False,
            set_status_on_exception=False,
        )
        if self.captures_content:
            self._annotate_span_io(
                span,
                input_value=input_value,
                output_value=output_value,
                trace_level=False,
            )
        if error_type:
            safe_type = str(redact(error_type))
            span.add_event("error", {"error.type": safe_type})
            span.set_status(Status(StatusCode.ERROR, safe_type))
        span.end(end_time=max(started_at_ns, ended_at_ns))

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
            content_capture=settings.otel_content_capture,
            content_max_chars=settings.otel_content_max_chars,
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
        content_capture=settings.otel_content_capture,
        content_max_chars=settings.otel_content_max_chars,
    )
