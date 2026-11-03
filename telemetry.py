"""Opt-in OTLP/HTTP tracing that exports metadata only.

Tracing is off unless an OTLP endpoint is set with the standard OTEL_* variables.
Spans carry a fixed set of attributes: HTTP method, route and status, the MCP tool
name, the Spond API operation and the error type. Never names, IDs, arguments,
messages or credentials.
"""

import os
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from settings import VERSION

SCOPE = "spond-mcp"
ALLOWED_ATTRIBUTES = {
    "http.request.method",
    "http.response.status_code",
    "http.route",
    "mcp.tool.name",
    "spond.operation",
    "error.type",
}
ROUTES = {"/mcp", "/config", "/healthz", "/health"}
METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}


def configure():
    """Configure once at startup; return a shutdown callback."""
    disabled = os.environ.get("OTEL_SDK_DISABLED", "false").lower()
    if disabled not in {"true", "false"}:
        raise ValueError("OTEL_SDK_DISABLED must be true or false")
    exporter = os.environ.get("OTEL_TRACES_EXPORTER", "otlp")
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if disabled == "true" or exporter == "none" or not endpoint:
        return lambda: None
    if exporter != "otlp":
        raise ValueError("OTEL_TRACES_EXPORTER must be otlp or none")
    protocol = os.environ.get(
        "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    )
    if protocol != "http/protobuf":
        raise ValueError("Only OTLP HTTP/protobuf is supported")
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Resource.create reads OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES; only fill in defaults.
    attributes = dict(Resource.create().attributes)
    if not os.environ.get("OTEL_SERVICE_NAME") and not any(
        item.strip().startswith("service.name=") for item in os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "").split(",")
    ):
        attributes["service.name"] = SCOPE
    attributes.setdefault("service.version", VERSION)
    provider = TracerProvider(resource=Resource(attributes))
    provider.add_span_processor(BatchSpanProcessor(PrivateExporter(OTLPSpanExporter())))
    trace.set_tracer_provider(provider)
    return provider.shutdown


@contextmanager
def span(name: str, *, kind=SpanKind.INTERNAL, attributes=None, context=None):
    with trace.get_tracer(SCOPE).start_as_current_span(
        name,
        kind=kind,
        attributes=attributes,
        context=context,
        record_exception=False,
        set_status_on_exception=False,
    ) as current:
        try:
            yield current
        except BaseException as error:
            mark_error(current, error)
            raise


def mark_error(current, error: BaseException) -> None:
    current.set_attribute("error.type", type(error).__name__)
    current.set_status(Status(StatusCode.ERROR, "Operation failed"))


class TraceHTTP:
    """ASGI middleware: one server span per request, continuing the gateway's trace."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or (scope["path"] in ("/healthz", "/health") and not scope.get("query_string")):
            return await self.app(scope, receive, send)
        route = scope["path"] if scope["path"] in ROUTES else "/{redacted}"
        method = scope.get("method", "OTHER")
        if method not in METHODS:
            method = "OTHER"
        # W3C trace context only; baggage and other headers are ignored.
        headers = {
            k.decode("latin1"): v.decode("latin1")
            for k, v in scope.get("headers", [])
            if k in (b"traceparent", b"tracestate")
        }
        parent = TraceContextTextMapPropagator().extract(headers)
        with span(
            f"{method} {route}",
            kind=SpanKind.SERVER,
            context=parent,
            attributes={"http.request.method": method, "http.route": route},
        ) as current:

            async def traced_send(message):
                if message["type"] == "http.response.start":
                    status = message["status"]
                    current.set_attribute("http.response.status_code", status)
                    if status >= 500:
                        current.set_status(Status(StatusCode.ERROR, "HTTP request failed"))
                await send(message)

            await self.app(scope, receive, traced_send)


class PrivateExporter:
    """Export only our own spans' allowed attributes; drop events, links and foreign attributes."""

    def __init__(self, delegate):
        self.delegate = delegate

    def export(self, spans):
        from opentelemetry.sdk.trace import ReadableSpan

        cleaned = []
        for original in spans:
            own = original.instrumentation_scope is not None and original.instrumentation_scope.name == SCOPE
            cleaned.append(
                ReadableSpan(
                    name=original.name if own else "span",
                    context=original.context,
                    parent=original.parent,
                    resource=original.resource,
                    attributes={
                        k: v for k, v in (original.attributes or {}).items() if own and k in ALLOWED_ATTRIBUTES
                    },
                    events=(),
                    links=(),
                    kind=original.kind,
                    status=Status(original.status.status_code),
                    start_time=original.start_time,
                    end_time=original.end_time,
                    instrumentation_scope=original.instrumentation_scope,
                )
            )
        return self.delegate.export(cleaned)

    def shutdown(self):
        return self.delegate.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.delegate.force_flush(timeout_millis)
