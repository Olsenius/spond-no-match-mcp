"""Tests for OpenTelemetry tracing: which spans exist and that they hold no personal data."""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

import telemetry

EXPORTED = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(telemetry.PrivateExporter(EXPORTED)))
trace.set_tracer_provider(_provider)

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PERSONAL = ["Oliver", "Emma", "Noah", "Hansen", "MEMBER_", "GUARDIAN_", "EVT_", "@example.com", "+479", "synthetic"]


@pytest.fixture(autouse=True)
def clear_spans():
    EXPORTED.clear()
    yield
    EXPORTED.clear()


@pytest.fixture
def client(make_client, monkeypatch, service):
    import main

    with make_client("") as c:
        monkeypatch.setattr(main, "service", service)
        yield c


def call(client, name, arguments, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    return client.post("/mcp", json=body, headers={**MCP_HEADERS, **(headers or {})})


def by_name(spans):
    return {s.name: s for s in spans}


class TestConfigure:
    def test_off_without_endpoint(self, monkeypatch):
        for var in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_SDK_DISABLED"):
            monkeypatch.delenv(var, raising=False)
        assert telemetry.configure()() is None

    def test_off_when_disabled(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
        assert telemetry.configure()() is None

    def test_rejects_bad_values(self, monkeypatch):
        monkeypatch.setenv("OTEL_SDK_DISABLED", "maybe")
        with pytest.raises(ValueError, match="OTEL_SDK_DISABLED"):
            telemetry.configure()
        monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
        with pytest.raises(ValueError, match="HTTP/protobuf"):
            telemetry.configure()


class TestSpans:
    def test_tool_call_spans(self, client):
        resp = call(client, "get_upcoming_events", {"kid_name": "Oliver"})
        assert resp.status_code == 200
        spans = by_name(EXPORTED.get_finished_spans())
        server = spans["POST /mcp"]
        assert server.kind == SpanKind.SERVER
        assert dict(server.attributes) == {
            "http.request.method": "POST",
            "http.route": "/mcp",
            "http.response.status_code": 200,
        }
        assert dict(spans["tool get_upcoming_events"].attributes) == {"mcp.tool.name": "get_upcoming_events"}
        upstream = [s for s in spans.values() if s.kind == SpanKind.CLIENT]
        assert {s.attributes["spond.operation"] for s in upstream} >= {"get_profile", "get_groups", "get_events"}
        assert all(s.context.trace_id == server.context.trace_id for s in spans.values())

    def test_continues_gateway_trace(self, client):
        call(client, "list_groups", {}, {"traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01"})
        server = by_name(EXPORTED.get_finished_spans())["POST /mcp"]
        assert format(server.context.trace_id, "032x") == TRACE_ID

    def test_no_personal_data_in_spans(self, client):
        for name, args in [
            ("get_upcoming_events", {"kid_name": "Oliver"}),
            ("get_event_participants", {"event_id": "EVT_TRENING_1"}),
            ("respond_to_event", {"event_id": "EVT_KAMP_1", "kid_name": "Oliver", "accept": True}),
            ("get_chat_messages", {"chat_id": "CHAT_1"}),
        ]:
            call(client, name, args)
        spans = EXPORTED.get_finished_spans()
        assert spans
        for s in spans:
            text = s.name + repr(dict(s.attributes)) + repr(s.events) + repr(s.status.description)
            for needle in PERSONAL:
                assert needle not in text, (s.name, needle)

    def test_unknown_tool_name_not_recorded(self, client):
        call(client, "Oliver's secret tool", {})
        names = {s.name for s in EXPORTED.get_finished_spans()}
        assert "tool unknown" in names
        assert not any("Oliver" in n for n in names)

    def test_errors_recorded_by_type_only(self, client, service):
        service._client.get_groups.side_effect = RuntimeError("Oliver's data")
        service.clear_cache()
        call(client, "list_groups", {})
        spans = by_name(EXPORTED.get_finished_spans())
        assert spans["spond get_groups"].attributes["error.type"] == "RuntimeError"
        assert spans["tool list_groups"].attributes["error.type"] == "RuntimeError"
        assert "Oliver" not in repr([s.status.description for s in spans.values()])

    def test_routes_redacted_and_liveness_untraced(self, client):
        client.get("/healthz")
        client.get("/health")
        client.get("/members/Oliver")
        names = {s.name for s in EXPORTED.get_finished_spans()}
        assert names == {"GET /{redacted}"}


class TestPrivateExporter:
    def test_strips_foreign_and_unknown_attributes(self):
        foreign = trace.get_tracer("some-library")
        with foreign.start_as_current_span("GET /members/Oliver", attributes={"url.full": "https://x/Oliver"}):
            pass
        with telemetry.span("tool list_groups", attributes={"mcp.tool.name": "list_groups", "user": "Oliver"}) as s:
            s.add_event("Oliver logged in")
        spans = EXPORTED.get_finished_spans()
        assert [(x.name, dict(x.attributes), x.events) for x in spans] == [
            ("span", {}, ()),
            ("tool list_groups", {"mcp.tool.name": "list_groups"}, ()),
        ]
