import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from harness.config import Settings
from harness.observability.provider import build_observability


def test_local_defaults_have_no_exporter() -> None:
    observability = build_observability(Settings())

    assert observability.enabled is False
    assert observability.exporter is None


def test_trace_context_propagates_api_to_worker_runtime() -> None:
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )

    with observability.span("api.run.create"):
        carrier = observability.inject()
    with observability.span("worker.run", carrier=carrier):
        with observability.span("runtime.execute"):
            pass

    spans = exporter.get_finished_spans()
    by_name = {span.name: span for span in spans}
    api_context = by_name["api.run.create"].context
    worker_context = by_name["worker.run"].context
    runtime_context = by_name["runtime.execute"].context
    assert api_context is not None
    assert worker_context is not None
    assert runtime_context is not None
    assert api_context.trace_id == worker_context.trace_id
    assert worker_context.trace_id == runtime_context.trace_id
    assert by_name["worker.run"].parent is not None
    assert by_name["runtime.execute"].parent is not None


def test_span_records_failure_without_exporting_sensitive_attributes() -> None:
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )

    with pytest.raises(RuntimeError, match="private failure body"):
        with observability.span(
            "protected.stage",
            attributes={
                "api_key": "top-secret",
                "memory.content": "private memory",
                "file.content": "private file",
                "item.count": 2,
            },
        ):
            raise RuntimeError("private failure body")

    span = exporter.get_finished_spans()[0]
    attributes = span.attributes
    assert attributes is not None
    assert span.status.status_code is StatusCode.ERROR
    assert attributes["api_key"] == "[REDACTED]"
    assert attributes["memory.content"] == "[REDACTED]"
    assert attributes["file.content"] == "[REDACTED]"
    assert attributes["item.count"] == 2
    assert "top-secret" not in repr(attributes)
    assert "private memory" not in repr(attributes)
    assert "private file" not in repr(attributes)
    assert all(
        "private failure body" not in repr(event.attributes)
        for event in span.events
    )
