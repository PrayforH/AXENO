from dataclasses import replace

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from harness.api.app import create_app
from harness.api.dependencies import build_memory_container
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


@pytest.mark.asyncio
async def test_api_request_continues_incoming_web_trace() -> None:
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )

    trace_id = "1234567890abcdef1234567890abcdef"
    parent_span_id = "1234567890abcdef"
    container = replace(
        build_memory_container(),
        observability=observability,
    )
    app = create_app(container)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/healthz",
            headers={
                "traceparent": f"00-{trace_id}-{parent_span_id}-01",
            },
        )

    assert response.status_code == 200
    spans = {span.name: span for span in exporter.get_finished_spans()}
    api = spans["harness.api.request"]
    assert api.context is not None
    assert api.context.trace_id == int(trace_id, 16)
    assert api.parent is not None
    assert f"{api.parent.span_id:016x}" == parent_span_id


def test_bound_attributes_propagate_to_nested_spans() -> None:
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )

    with observability.bind_attributes({"langfuse.session.id": "session-a"}):
        with observability.span("run.root"):
            with observability.span("run.child"):
                pass

    spans = exporter.get_finished_spans()
    assert {span.name for span in spans} == {"run.root", "run.child"}
    assert all(
        span.attributes is not None and span.attributes["langfuse.session.id"] == "session-a"
        for span in spans
    )


def test_distinct_traces_can_share_a_langfuse_session() -> None:
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )

    with observability.bind_attributes({"langfuse.session.id": "session-a"}):
        with observability.span("run.one"):
            pass
        with observability.span("run.two"):
            pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    assert spans[0].context is not None
    assert spans[1].context is not None
    assert spans[0].context.trace_id != spans[1].context.trace_id
    assert {
        span.attributes["langfuse.session.id"]  # type: ignore[index]
        for span in spans
    } == {"session-a"}


def test_trace_resource_labels_the_deployment_environment() -> None:
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(
            otel_enabled=True,
            otlp_endpoint="http://unused/v1/traces",
            otel_environment="staging",
        ),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )

    with observability.span("environment.check"):
        pass

    resource = exporter.get_finished_spans()[0].resource
    assert resource.attributes["service.name"] == "claude-agent-harness"
    assert resource.attributes["deployment.environment.name"] == "staging"


def test_trace_content_is_opt_in_redacted_and_bounded() -> None:
    disabled_exporter = InMemorySpanExporter()
    disabled = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=disabled_exporter,
        processor_factory=SimpleSpanProcessor,
    )
    with disabled.span("content.off"):
        disabled.annotate_current_io(
            input_value="private question",
            output_value="private answer",
            trace_level=True,
        )
    disabled_attributes = disabled_exporter.get_finished_spans()[0].attributes
    assert disabled_attributes is not None
    assert "langfuse.trace.input" not in disabled_attributes
    assert "langfuse.trace.output" not in disabled_attributes

    exporter = InMemorySpanExporter()
    enabled = build_observability(
        Settings(
            otel_enabled=True,
            otlp_endpoint="http://unused/v1/traces",
            otel_content_capture="redacted",
            otel_content_max_chars=256,
        ),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )
    with enabled.span("content.redacted"):
        enabled.annotate_current_io(
            input_value="question token=top-secret " + ("context " * 80),
            output_value="answer authorization: Bearer private-value",
            trace_level=True,
        )
    attributes = exporter.get_finished_spans()[0].attributes
    assert attributes is not None
    trace_input = str(attributes["langfuse.trace.input"])
    assert len(trace_input) == 256
    assert trace_input.endswith("…")
    assert attributes["langfuse.observation.input"] == trace_input
    assert attributes["langfuse.trace.output"] == (
        "answer authorization: [REDACTED]"
    )
    assert attributes["langfuse.observation.output"] == (
        "answer authorization: [REDACTED]"
    )
    assert "top-secret" not in repr(attributes)
    assert "private-value" not in repr(attributes)


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
    assert all("private failure body" not in repr(event.attributes) for event in span.events)


def test_trace_attribute_allowlist_drops_raw_io_and_unknown_fields() -> None:
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )
    with observability.span(
        "allowlist",
        attributes={
            "run.id": "run-a",
            "tool.arguments": "private argument",
            "answer": "private answer",
            "harness.prompt": "private prompt",
        },
    ):
        pass
    attributes = exporter.get_finished_spans()[0].attributes
    assert attributes is not None
    assert attributes["run.id"] == "run-a"
    assert attributes["harness.prompt"] == "[REDACTED]"
    assert "tool.arguments" not in attributes
    assert "answer" not in attributes
    assert "private" not in repr(attributes)
