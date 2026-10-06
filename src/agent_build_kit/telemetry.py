"""OpenTelemetry traces and metrics for the pipeline, off unless enabled.

`init()` builds the providers when `ABK_OTEL_ENABLED` is set and the
`telemetry` extra is installed; `tracer()` and `meter()` are no-ops otherwise,
so call sites never branch on the switch. `shutdown()` flushes within a bound.
Telemetry never affects a run: export failures are swallowed.

The SDK is imported only inside `init()`, so a plain install, or a run with the
switch off, imports no OpenTelemetry module.
"""

from __future__ import annotations

import atexit
import logging
import threading
from collections.abc import Callable
from typing import Any

from agent_build_kit.settings import settings

log = logging.getLogger(__name__)

# Seconds an exporter may spend on one request. shutdown() flushes the trace
# and metric providers in turn, so it can take up to about two of these.
EXPORT_TIMEOUT = 3.0
METRIC_INTERVAL_MS = 30_000

_lock = threading.Lock()
_tracer_provider: Any = None
_meter_provider: Any = None
_atexit_registered = False


class _NoSpanContext:
    """What a no-op span reports as its context: no trace, no span."""

    trace_id = 0
    span_id = 0
    is_valid = False


class _NoOp:
    """Accepts every call and attribute, returning itself; a context manager.

    Called with a single function it hands the function back, so the decorator
    form `@tracer().start_as_current_span("x")` leaves the function alone.
    """

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if len(args) == 1 and not kwargs and callable(args[0]):
            return args[0]
        return self

    def is_recording(self) -> bool:
        return False

    def get_span_context(self) -> _NoSpanContext:
        return _NoSpanContext()

    def __enter__(self) -> _NoOp:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


_NOOP = _NoOp()

EXPORTER_LOGGERS = (
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.exporter.otlp.proto.http.metric_exporter",
)


class _Downgrade(logging.Filter):
    """The exporters log a failed export as an error; for the pipeline an
    unreachable collector is at most a warning."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno > logging.WARNING:
            record.levelno, record.levelname = logging.WARNING, "WARNING"
        return True


_DOWNGRADE = _Downgrade()


def _endpoint(specific: str, shared: str, path: str) -> str | None:
    if specific:
        return specific
    if shared:
        return shared.rstrip("/") + path
    return None


def _resource_attributes() -> dict[str, str]:
    attributes: dict[str, str] = {}
    for pair in settings.otel_resource_attributes.split(","):
        key, sep, value = pair.partition("=")
        if sep and key.strip():
            attributes[key.strip()] = value.strip()
    attributes["service.name"] = settings.otel_service_name
    return attributes


def init() -> bool:
    """Install the providers; True when telemetry is on."""
    global _tracer_provider, _meter_provider, _atexit_registered
    if not settings.otel_enabled:
        return False
    with _lock:
        if _tracer_provider is not None:
            return True
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import (
                MetricExportResult,
                MetricsData,
                PeriodicExportingMetricReader,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult
        except ImportError:
            log.warning(
                "telemetry is enabled but the `telemetry` extra is not installed; "
                "continuing without it (install agent-build-kit[telemetry])"
            )
            return False

        class SafeSpanExporter(OTLPSpanExporter):
            def export(self, spans: Any) -> Any:
                try:
                    return super().export(spans)
                except Exception as exc:
                    log.warning("telemetry: span export failed: %s", type(exc).__name__)
                    return SpanExportResult.FAILURE

        class SafeMetricExporter(OTLPMetricExporter):
            def export(
                self,
                metrics_data: MetricsData,
                timeout_millis: float | None = 10_000,
                **kwargs: Any,
            ) -> MetricExportResult:
                try:
                    return super().export(metrics_data, timeout_millis, **kwargs)
                except Exception as exc:
                    log.warning("telemetry: metric export failed: %s", type(exc).__name__)
                    return MetricExportResult.FAILURE

        for name in EXPORTER_LOGGERS:
            logging.getLogger(name).addFilter(_DOWNGRADE)
        shared = settings.otel_exporter_otlp_endpoint
        resource = Resource.create(_resource_attributes())
        traces = _endpoint(settings.otel_exporter_otlp_traces_endpoint, shared, "/v1/traces")
        metrics = _endpoint(settings.otel_exporter_otlp_metrics_endpoint, shared, "/v1/metrics")
        try:
            tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    SafeSpanExporter(endpoint=traces, timeout=EXPORT_TIMEOUT),
                    export_timeout_millis=int(EXPORT_TIMEOUT * 1000),
                )
            )
            reader = PeriodicExportingMetricReader(
                SafeMetricExporter(endpoint=metrics, timeout=EXPORT_TIMEOUT),
                export_interval_millis=METRIC_INTERVAL_MS,
                export_timeout_millis=int(EXPORT_TIMEOUT * 1000),
            )
            meter_provider = MeterProvider(
                resource=resource, metric_readers=[reader], shutdown_on_exit=False
            )
        except Exception as exc:
            log.warning("telemetry: could not start (%s); continuing without it", exc)
            return False
        _tracer_provider, _meter_provider = tracer_provider, meter_provider
        if not _atexit_registered:
            atexit.register(shutdown)
            _atexit_registered = True
        return True


def _safely(call: Callable[[], object]) -> None:
    try:
        call()
    except Exception as exc:
        log.warning("telemetry: could not record a metric: %s", type(exc).__name__)


# Seconds, for the duration histograms: the SDK's own default buckets are
# milliseconds, which would put every step in the last one.
DURATION_BUCKETS = [1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200]


def duration(name: str, seconds: float, **attributes: str) -> None:
    """Record `seconds` in the histogram `name`."""
    _safely(
        lambda: (
            meter()
            .create_histogram(name, unit="s", explicit_bucket_boundaries_advisory=DURATION_BUCKETS)
            .record(seconds, attributes)
        )
    )


def observe(name: str, value: float, **attributes: str) -> None:
    """Record `value` in the histogram `name`."""
    _safely(lambda: meter().create_histogram(name).record(value, attributes))


def count(name: str, value: int = 1, **attributes: str | int | Callable[[], str | int]) -> None:
    """Add `value` to the counter `name`.

    An attribute may be a callable, called only inside the guard: one that is
    costly or may raise is not run with telemetry off, and cannot fail the run
    when it is on."""

    def add() -> None:
        resolved = {k: v() if callable(v) else v for k, v in attributes.items()}
        meter().create_counter(name).add(value, resolved)

    _safely(add)


def level(name: str, value: int, **attributes: str) -> None:
    """Set the gauge `name`."""
    _safely(lambda: meter().create_gauge(name).set(value, attributes))


def reference(span: Any) -> str:
    """Where `span` is, as text a later run can link to; empty when telemetry
    is off."""
    context = span.get_span_context()
    if not context.is_valid:
        return ""
    return f"{context.trace_id:032x}-{context.span_id:016x}"


def links(earlier: str) -> list[Any]:
    """The span links that point at the span `reference` named."""
    trace, _, span = earlier.partition("-")
    if not (trace and span and _tracer_provider is not None):
        return []
    try:
        from opentelemetry.trace import Link, SpanContext

        return [Link(SpanContext(int(trace, 16), int(span, 16), is_remote=True))]
    except (ImportError, ValueError):
        return []


# What every span is opened with: the SDK's defaults would export an
# exception's text and stack as an event and in the status, and the text of a
# failure (a gate's output, a diff) is never to leave the process.
SPAN_OPTIONS: dict[str, bool] = {"record_exception": False, "set_status_on_exception": False}


def failed(span: Any) -> None:
    """Mark `span` as an error, with no description: the kind of failure is
    the `outcome` attribute, never the exception's text."""
    if not span.is_recording():
        return
    _safely(lambda: span.set_status(_error_status()))


def _error_status() -> Any:
    from opentelemetry.trace import Status, StatusCode

    return Status(StatusCode.ERROR)


def tracer() -> Any:
    """The tracer, or a no-op that accepts every call."""
    provider = _tracer_provider
    if provider is None:
        return _NOOP
    return provider.get_tracer("agent_build_kit")


def meter() -> Any:
    """The meter, or a no-op that accepts every call."""
    provider = _meter_provider
    if provider is None:
        return _NOOP
    return provider.get_meter("agent_build_kit")


def shutdown() -> None:
    """Flush pending telemetry within a bounded time and stop exporting."""
    global _tracer_provider, _meter_provider
    with _lock:
        tracer_provider, meter_provider = _tracer_provider, _meter_provider
        _tracer_provider = _meter_provider = None
    for provider in (tracer_provider, meter_provider):
        if provider is None:
            continue
        try:
            provider.shutdown()
        except Exception as exc:
            log.warning("telemetry: shutdown failed: %s", type(exc).__name__)
