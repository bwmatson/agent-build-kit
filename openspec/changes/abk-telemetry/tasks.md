# Tasks

Acceptance: group 3 drives a tick with telemetry on against the shared stack's
dev instance, as a real producer, and reads the span and metrics back from the
stack's own query APIs. Groups 1 and 2 prove what is sent with an in-process
receiver; the platform's intake is the separate change `telemetry-intake`.

## 1. [agent-build-kit] [unit-test] The telemetry module, off by default

Done when `abk tick` can emit traces and metrics through standard `OTEL_*`
settings, does nothing when the switch is off, and cannot be made to fail or
slow by a bad collector.

- [x] 1.1 Test: with the switch off, `init()` returns false, imports no OTel
      module, and `tracer()` / `meter()` return no-ops that accept every call.
- [x] 1.2 Test: with it on and the extra missing, one line says so and `init()`
      returns false.
- [x] 1.3 Test: with it on, a span and a metric recorded in a tick arrive at an
      in-process OTLP/HTTP receiver, at the per-signal endpoints when both
      are set and at the shared one otherwise.
- [x] 1.4 Test: an exporter whose `export()` raises, and an endpoint that does
      not answer, leave the caller unaffected and log at most a warning, and
      `shutdown()` returns within its bound.
- [x] 1.5 Add the settings (`ABK_OTEL_ENABLED`, the standard `OTEL_*` names)
      to `settings.py`, the `telemetry` extra to `pyproject.toml`, and
      `telemetry.py` with `init`, `tracer`, `meter` and `shutdown`.
- [x] 1.6 Have `abk doctor` warn on an enabled switch with no endpoint or an
      unreachable one, and document the settings in `docs/configuration.md`
      and the `abk-config` skill.

## 2. [agent-build-kit] [unit-test] Spans and metrics for the shape of a run

Done when a tick's unit runs are traced from tick to agent call with the
attributes the spec names, the metrics table is recorded, and no attribute
carries prompts, diffs, feedback or commit messages.

- [x] 2.1 Test: a unit with two review rounds produces a tick span, a unit
      span, step spans including one per round, and an agent span below each
      agent step, with the identifier, change, step, round, runtime, model and
      outcome attributes.
- [x] 2.2 Test: the unit spans of units built in parallel threads belong to the
      tick's trace, and a unit resumed in a later tick links to its earlier
      trace.
- [x] 2.3 Test: no span or metric attribute contains the text of feedback,
      a prompt, a diff or a commit message; unit ids and change names appear on
      spans and on no metric.
- [x] 2.4 Test: the table's instruments are recorded for a unit that is built,
      reviewed twice and pushed, for a usage pause, and for a reclaimed unit;
      a runtime without token counts emits turns and duration only.
- [x] 2.5 Test: a tick flushes before returning, so a receiver sees the tick's
      spans and metrics.
- [x] 2.6 Instrument the tick, the stack runner's steps, the agent runtimes and
      the usage guard, passing the context into each unit's worker; reuse the
      same tracer for the graph engine's node spans.
- [x] 2.7 Compare `docs/architecture.md` and `docs/unit-graph.md` with what
      this group built, add a telemetry section describing the spans and
      metrics, and update the changelog.

## 3. [agent-build-kit] [e2e-test] [acceptance] A tick's telemetry arrives in the shared stack

Needs: telemetry-intake group 1 merged — the metrics store must already accept OTLP metrics for the tick's metrics to land
Needs: tempo-query-port group 1 merged — the test finds the trace through the trace store's query API, which the platform must publish on the host

Done when a tick run against a fixture planning repo with telemetry enabled
leaves its trace in the stack's trace store and its metrics in the metrics
store, found by the queries a person would use.

- [x] 3.1 Test (`local_stack`): with the shared stack's dev instance up and
      telemetry pointed at its trace and metrics intake, a tick that builds a
      fixture unit leaves a trace whose root is the tick, with a unit span and
      a step span below it, found through the trace store's search API by the
      unit id.
- [x] 3.2 Test (`local_stack`): the same tick's `abk.unit.duration` and
      `abk.step.duration` series are returned by the metrics store's query API
      with the repo, tier and outcome attributes, and no series carries a unit
      id.
- [x] 3.3 Test (`local_stack`): with the endpoint pointing at nothing, the same
      tick finishes with the same outcome and no trace or series is written.
- [x] 3.4 Write the acceptance run: start the fixture tick with the switch and
      both intake endpoints taken from the dev stack's published ports, wait
      for the flush, and query both stores.
- [x] 3.5 Describe how to run it, and what it needs up, in `docs/` and the
      changelog.
