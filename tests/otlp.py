"""An in-process OTLP/HTTP receiver that decodes the real protobuf bodies the
exporters post, into the spans and metric points a test asserts on.

`enabled` points telemetry at it through the settings a person would set.
"""

from __future__ import annotations

import gzip
import http.server
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent_build_kit import telemetry
from agent_build_kit.settings import reload

ENV_KEYS = (
    "ABK_OTEL_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_SERVICE_NAME",
    "OTEL_RESOURCE_ATTRIBUTES",
)


def _value(any_value: Any) -> Any:
    kind = any_value.WhichOneof("value")
    return getattr(any_value, kind) if kind else None


def _attributes(pairs: Any) -> dict[str, Any]:
    return {pair.key: _value(pair.value) for pair in pairs}


@dataclass(frozen=True)
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_id: str
    attributes: dict[str, Any]
    links: tuple[str, ...]  # the trace id of each link
    status_message: str
    events: tuple[tuple[str, dict[str, Any]], ...]

    def texts(self) -> list[str]:
        """Every string this span carries beyond its name."""
        values = [*self.attributes.values(), self.status_message]
        for name, attributes in self.events:
            values += [name, *attributes.values()]
        return [value for value in values if isinstance(value, str)]


@dataclass(frozen=True)
class Point:
    metric: str
    attributes: dict[str, Any]
    value: float  # a sum or gauge's value; a histogram's sum
    count: int | None  # a histogram's count, otherwise None


@dataclass
class Collector:
    port: int
    posts: list[tuple[str, bytes]] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def spans(self) -> list[Span]:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        found = []
        for path, body in list(self.posts):
            if path != "/v1/traces":
                continue
            for resource in ExportTraceServiceRequest.FromString(body).resource_spans:
                for scope in resource.scope_spans:
                    for span in scope.spans:
                        found.append(
                            Span(
                                name=span.name,
                                trace_id=span.trace_id.hex(),
                                span_id=span.span_id.hex(),
                                parent_id=span.parent_span_id.hex(),
                                attributes=_attributes(span.attributes),
                                links=tuple(link.trace_id.hex() for link in span.links),
                                status_message=span.status.message,
                                events=tuple(
                                    (event.name, _attributes(event.attributes))
                                    for event in span.events
                                ),
                            )
                        )
        return found

    def points(self) -> list[Point]:
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
            ExportMetricsServiceRequest,
        )

        found = []
        for path, body in list(self.posts):
            if path != "/v1/metrics":
                continue
            for resource in ExportMetricsServiceRequest.FromString(body).resource_metrics:
                for scope in resource.scope_metrics:
                    for metric in scope.metrics:
                        kind = metric.WhichOneof("data")
                        assert kind is not None
                        for point in getattr(metric, kind).data_points:
                            if kind == "histogram":
                                value, count = point.sum, point.count
                            else:
                                value, count = getattr(point, point.WhichOneof("value")), None
                            found.append(
                                Point(metric.name, _attributes(point.attributes), value, count)
                            )
        return found

    def metric(self, name: str) -> list[Point]:
        return [point for point in self.points() if point.metric == name]


@contextmanager
def serving() -> Iterator[Collector]:
    posts: list[tuple[str, bytes]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            posts.append((self.path, body))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Collector(port=server.server_address[1], posts=posts)
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def enabled() -> Iterator[Collector]:
    """Telemetry switched on and pointed at a collector. It is left to the code
    under test to initialise and to flush; only the teardown shuts down."""
    with pytest.MonkeyPatch.context() as env, serving() as collector:
        for key in ENV_KEYS:
            env.delenv(key, raising=False)
        env.setenv("ABK_OTEL_ENABLED", "true")
        env.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.url)
        reload(None)
        try:
            yield collector
        finally:
            telemetry.shutdown()
            env.undo()
            reload(None)
