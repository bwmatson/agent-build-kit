"""The telemetry module: off by default, and never able to affect a run.

What is sent is proved with an in-process OTLP/HTTP receiver that decodes the
real protobuf bodies the exporters post.
"""

from __future__ import annotations

import gzip
import http.server
import logging
import socket
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest

from agent_build_kit import telemetry
from agent_build_kit.settings import reload

SHUTDOWN_BOUND = 10.0
ENV_KEYS = (
    "ABK_OTEL_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_SERVICE_NAME",
    "OTEL_RESOURCE_ATTRIBUTES",
)


@dataclass
class Receiver:
    port: int
    posts: list[tuple[str, bytes]] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def paths(self) -> list[str]:
        return [path for path, _ in self.posts]

    def span_names(self, path: str) -> list[str]:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        names = []
        for posted, body in self.posts:
            if posted != path:
                continue
            request = ExportTraceServiceRequest.FromString(body)
            names += [
                span.name
                for resource in request.resource_spans
                for scope in resource.scope_spans
                for span in scope.spans
            ]
        return names

    def metric_names(self, path: str) -> list[str]:
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
            ExportMetricsServiceRequest,
        )

        names = []
        for posted, body in self.posts:
            if posted != path:
                continue
            request = ExportMetricsServiceRequest.FromString(body)
            names += [
                metric.name
                for resource in request.resource_metrics
                for scope in resource.scope_metrics
                for metric in scope.metrics
            ]
        return names


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    yield from serve(200)


def serve(status: int) -> Iterator[Receiver]:
    posts: list[tuple[str, bytes]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            posts.append((self.path, body))
            self.send_response(status)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Receiver(port=server.server_address[1], posts=posts)
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(params=[503, 429])
def overloaded_receiver(request: pytest.FixtureRequest) -> Iterator[Receiver]:
    """A collector that answers every export with a retryable error."""
    yield from serve(request.param)


@pytest.fixture
def closed_port() -> str:
    """An endpoint nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


@pytest.fixture
def silent_endpoint() -> Iterator[str]:
    """An endpoint that accepts connections and never answers."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        sock.close()


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Set telemetry settings through the environment and re-read them."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def apply(**env: str) -> None:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        reload(None)

    reload(None)
    yield apply
    telemetry.shutdown()
    monkeypatch.undo()
    reload(None)


NO_OP_SCRIPT = textwrap.dedent(
    """
    import sys
    from agent_build_kit import telemetry

    assert telemetry.init() is False
    with telemetry.tracer().start_as_current_span("tick", attributes={"a": 1}) as span:
        span.set_attribute("k", "v")
        span.add_event("e", {"x": 1})
        span.set_status("ok")
        span.record_exception(ValueError("x"))
    telemetry.tracer().start_span("s").end()
    meter = telemetry.meter()
    meter.create_counter("c", unit="1", description="d").add(1, {"a": "b"})
    meter.create_histogram("h").record(1.5, {"a": "b"})
    meter.create_up_down_counter("u").add(-1)
    meter.create_gauge("g").set(3, {"a": "b"})
    telemetry.shutdown()

    @telemetry.tracer().start_as_current_span("s")
    def decorated():
        return 7

    assert decorated() == 7
    assert telemetry.tracer().start_span("s").is_recording() is False
    loaded = sorted(m for m in sys.modules if m.split(".")[0] == "opentelemetry")
    print("LOADED:" + ",".join(loaded))
    """
)


def test_off_by_default_init_is_false_and_no_otel_module_is_imported() -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
    done = subprocess.run(
        [sys.executable, "-c", NO_OP_SCRIPT],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == "LOADED:"


def test_the_no_op_tracer_and_meter_are_safe_in_process(configure) -> None:
    assert telemetry.init() is False
    with telemetry.tracer().start_as_current_span("tick") as span:
        span.set_attribute("k", "v")
    telemetry.meter().create_counter("c").add(1)
    telemetry.shutdown()


def test_the_no_op_leaves_a_decorated_function_running(configure) -> None:
    assert telemetry.init() is False

    @telemetry.tracer().start_as_current_span("s")
    def build(unit: str, *, retries: int = 0) -> str:
        return f"{unit}:{retries}"

    assert build("u", retries=2) == "u:2"
    span = telemetry.tracer().start_span("s")
    assert span.is_recording() is False
    assert span.get_span_context().trace_id == 0
    assert span.get_span_context().span_id == 0


def test_enabled_without_the_extra_says_so_in_one_line(
    configure, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    configure(ABK_OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:9")
    # A None entry makes an import of that exact name raise ImportError, and
    # the import system looks the full dotted name up first, so submodules an
    # earlier test already imported are hidden one by one.
    for name in ["opentelemetry", *(m for m in sys.modules if m.startswith("opentelemetry."))]:
        monkeypatch.setitem(sys.modules, name, None)

    with caplog.at_level(logging.DEBUG):
        assert telemetry.init() is False

    lines = [r for r in caplog.records if "telemetry" in r.getMessage().lower()]
    assert len(lines) == 1
    assert "extra" in lines[0].getMessage()
    # The pipeline carries on with no-ops.
    with telemetry.tracer().start_as_current_span("tick"):
        pass
    telemetry.meter().create_counter("c").add(1)


def test_shared_endpoint_receives_both_signals_at_the_standard_paths(
    configure, receiver: Receiver
) -> None:
    configure(ABK_OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT=receiver.url)

    assert telemetry.init() is True
    with telemetry.tracer().start_as_current_span("tick"):
        telemetry.meter().create_counter("abk.test.counter").add(1, {"outcome": "ok"})
    telemetry.shutdown()

    assert "tick" in receiver.span_names("/v1/traces")
    assert "abk.test.counter" in receiver.metric_names("/v1/metrics")


def test_per_signal_endpoints_override_the_shared_one(configure, receiver: Receiver) -> None:
    configure(
        ABK_OTEL_ENABLED="true",
        OTEL_EXPORTER_OTLP_ENDPOINT=receiver.url + "/shared",
        OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=receiver.url + "/intake/traces",
        OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=receiver.url + "/intake/metrics",
    )

    assert telemetry.init() is True
    with telemetry.tracer().start_as_current_span("tick"):
        telemetry.meter().create_counter("abk.test.counter").add(1)
    telemetry.shutdown()

    assert "tick" in receiver.span_names("/intake/traces")
    assert "abk.test.counter" in receiver.metric_names("/intake/metrics")
    assert not any(path.startswith("/shared") for path in receiver.paths())


def test_the_service_name_reaches_the_resource(configure, receiver: Receiver) -> None:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    configure(
        ABK_OTEL_ENABLED="true",
        OTEL_EXPORTER_OTLP_ENDPOINT=receiver.url,
        OTEL_SERVICE_NAME="svc-a",
    )
    assert telemetry.init() is True
    with telemetry.tracer().start_as_current_span("tick"):
        pass
    telemetry.shutdown()

    request = ExportTraceServiceRequest.FromString(
        next(body for path, body in receiver.posts if path == "/v1/traces")
    )
    attributes = {
        kv.key: kv.value.string_value for kv in request.resource_spans[0].resource.attributes
    }
    assert attributes["service.name"] == "svc-a"


def test_an_exporter_whose_export_raises_leaves_the_caller_alone(
    configure,
    receiver: Receiver,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    def boom(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("exporter exploded")

    monkeypatch.setattr(OTLPSpanExporter, "export", boom)
    monkeypatch.setattr(OTLPMetricExporter, "export", boom)
    configure(ABK_OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT=receiver.url)

    with caplog.at_level(logging.DEBUG):
        assert telemetry.init() is True
        with telemetry.tracer().start_as_current_span("tick") as span:
            span.set_attribute("k", "v")
            telemetry.meter().create_histogram("abk.test.h").record(1.0)
            result = "unit built"
        started = time.monotonic()
        telemetry.shutdown()

    assert result == "unit built"
    assert time.monotonic() - started < SHUTDOWN_BOUND
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


@pytest.mark.parametrize("kind", ["closed", "silent"])
def test_an_endpoint_that_does_not_answer_neither_delays_nor_fails_the_caller(
    configure,
    closed_port: str,
    silent_endpoint: str,
    caplog: pytest.LogCaptureFixture,
    kind: str,
) -> None:
    endpoint = closed_port if kind == "closed" else silent_endpoint
    configure(ABK_OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT=endpoint)

    with caplog.at_level(logging.DEBUG):
        assert telemetry.init() is True
        started = time.monotonic()
        for _ in range(50):
            with telemetry.tracer().start_as_current_span("step"):
                telemetry.meter().create_counter("abk.test.counter").add(1)
        assert time.monotonic() - started < 2.0

        started = time.monotonic()
        telemetry.shutdown()
        assert time.monotonic() - started < SHUTDOWN_BOUND

    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_a_collector_answering_with_a_retryable_error_neither_delays_nor_fails_the_caller(
    configure, overloaded_receiver: Receiver, caplog: pytest.LogCaptureFixture
) -> None:
    configure(ABK_OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT=overloaded_receiver.url)

    with caplog.at_level(logging.DEBUG):
        assert telemetry.init() is True
        started = time.monotonic()
        for _ in range(50):
            with telemetry.tracer().start_as_current_span("step"):
                telemetry.meter().create_counter("abk.test.counter").add(1)
        assert time.monotonic() - started < 2.0

        started = time.monotonic()
        telemetry.shutdown()
        assert time.monotonic() - started < SHUTDOWN_BOUND

    assert overloaded_receiver.posts, "the collector was never asked"
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_an_exception_in_the_callers_span_still_propagates(configure, receiver: Receiver) -> None:
    configure(ABK_OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT=receiver.url)
    telemetry.init()

    with pytest.raises(ValueError, match="own failure"):
        with telemetry.tracer().start_as_current_span("unit"):
            raise ValueError("the unit's own failure")
