"""OpenTelemetry traces and metrics for the pipeline, off unless enabled.

`init()` builds the providers when `ABK_OTEL_ENABLED` is set and the
`telemetry` extra is installed; `tracer()` and `meter()` are no-ops otherwise,
so call sites never branch on the switch. `shutdown()` flushes within a bound.
Telemetry never affects a run: export failures are swallowed.
"""

from __future__ import annotations

from typing import Any


def init() -> bool:
    """Install the providers; True when telemetry is on."""
    raise NotImplementedError


def tracer() -> Any:
    """The tracer, or a no-op that accepts every call."""
    raise NotImplementedError


def meter() -> Any:
    """The meter, or a no-op that accepts every call."""
    raise NotImplementedError


def shutdown() -> None:
    """Flush pending telemetry within a bounded time and stop exporting."""
    raise NotImplementedError
