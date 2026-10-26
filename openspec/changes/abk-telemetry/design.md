# Design

## Configuration

Settings are machine-level, read through `settings.py` (pydantic-settings, no
`os.environ` elsewhere) using the standard OpenTelemetry names, so any
collector setup works unchanged:

- `ABK_OTEL_ENABLED` (default false): the single switch. Nothing else is read
  or imported when it is false.
- `OTEL_EXPORTER_OTLP_ENDPOINT`, with `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` and
  `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` overriding it per signal: traces and
  metrics usually go to different intake ports.
- `OTEL_SERVICE_NAME` (default `agent-build-kit`) and
  `OTEL_RESOURCE_ATTRIBUTES`, passed through to the resource.

`abk doctor` reports a missing endpoint or an unreachable collector as a
warning when telemetry is enabled, never an error.

## Dependencies

`opentelemetry-sdk` and the OTLP/HTTP exporters are an optional extra
(`telemetry`). Without the extra, enabling the switch logs one line saying the
extra is missing and carries on. The code imports the SDK lazily so a plain
install pays nothing.

## The module

`agent_build_kit/telemetry.py` exposes:

- `init()`, called once at the top of `abk tick` (and any long-lived
  command): builds providers, installs them, returns whether telemetry is on;
- `tracer()` and `meter()` returning no-op implementations when it is off, so
  call sites never branch on the switch;
- `shutdown()`, flushing within a bounded time, run at the end of a tick and
  from an `atexit` hook.

The exporter wrapper catches everything `export()` raises and downgrades it to
a warning: telemetry must not be able to take down a tick. Batching is on, so a
slow collector never blocks a step.

## Spans

```
tick
 └─ unit run            unit.id, change, repo, tier, base, resumed_from
     ├─ step            step (tests|implement|checks|review|rework|adapt|
     │                   unit-test|e2e-test|verify_base|push|open_pr), round
     │   └─ agent       runtime, model, role, turns, outcome
     └─ …
```

Attributes are identifiers and counts only. Outcome is one of the run's
statuses and, for a failure, its category (not its text). Errors are recorded as
span status, not as the message when the message could carry code or feedback.

Trace context crosses the tick's thread pool by passing the context
explicitly to each unit's worker, since contextvars do not follow a
`ThreadPoolExecutor` submit. A resumed unit starts a new trace linked to the
earlier run's trace id, recorded on the unit, so a unit's life across ticks can
be followed.

## Metrics

| Instrument | Kind | Attributes |
|---|---|---|
| `abk.tick.duration` | histogram | outcome |
| `abk.unit.duration` | histogram | repo, tier, outcome |
| `abk.step.duration` | histogram | step, outcome |
| `abk.review.rounds` | histogram | repo, outcome |
| `abk.checks.failures` | counter | check (lint, test, types), round |
| `abk.agent.turns` | histogram | role, model |
| `abk.agent.tokens` | counter | role, model, kind (input, output, cache) |
| `abk.usage.pauses` | counter | kind (usage, rate_limit) |
| `abk.units.reclaimed` | counter | |
| `abk.units` | gauge | state (planned, running, in_review, held, failed) |

Token counts are recorded only where the runtime's output carries them; a
runtime that does not simply emits no token series. Cardinality is bounded: unit
id and change name are on spans, never on metrics.

## Intake

Traces go to Tempo's OTLP/HTTP receiver. Metrics need a receiver on the
metrics store: Prometheus pulls, and a tick is too short-lived to be scraped,
so the store's OTLP receiver is enabled and metrics are pushed to it. A
dashboard provisioned beside the existing ones shows the table above. These
live in the platform repo and are the separate change `telemetry-intake`: a
change's groups are built one after another, and the two share no code.

## Out of scope

Logs (the run logs are already files a log shipper can tail); tracing the code
host and git subprocesses individually (they appear as step time); changing
what a run does in response to what it measures.
