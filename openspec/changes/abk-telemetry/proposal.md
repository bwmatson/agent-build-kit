# Proposal

## Why

The pipeline is a long-running, unattended system with several expensive and
failure-prone parts: agent runs, review rounds, unit-test checks, restacks, usage
pauses, forge polling. What is known about it today comes from per-unit run
logs and the journal. Those answer "what happened to this unit" and nothing
about the rest:

- where a unit's wall-clock time goes (building, reviewing, waiting for a
  slot, paused for usage);
- how many review and fix-check rounds units take, and which checks fail;
- how often a tick pauses, reclaims a stale unit, or fails at the push gate;
- what the agents cost in turns and tokens, by step and model;
- whether a change took an hour or two days from plan to merge.

Questions like "why was that tick 40 minutes", "is review getting slower", or
"which step burns the usage window" need numbers over time.

The platform the pipeline runs beside already collects exactly this kind of
data for its services: spans go to Tempo over OTLP, metrics and logs to
Prometheus and Loki, all viewed in Grafana. The pipeline is a producer that
isn't connected to it.

## What Changes

- **A small telemetry module in the framework.** It reads standard `OTEL_*`
  settings through the framework's settings class, builds a tracer and meter
  provider when enabled, and does nothing when it is not. It is the framework's
  own code: an installation's shared helper packages are not a dependency, since
  the framework must not know about any installation.
- **Spans for the shape of a run.** A tick, each unit's run, each step within
  it (tests, implement, checks, review rounds, rework, restack, push, open PR),
  and each agent call with its model, runtime, turns and outcome. The graph
  engine's node spans use the same tracer.
- **Metrics for the questions above.** Counters and histograms for unit and
  step durations, review and check rounds, outcomes by reason, usage pauses,
  stale reclaims, agent turns and, where the runtime reports them, tokens.
- **Telemetry never affects a run.** Exporting is asynchronous, bounded and
  swallowed on failure; a tick that cannot reach the collector runs exactly as
  it would with telemetry off. The process flushes before it exits, since a tick
  is short-lived.
- **The platform accepts it.** The metrics store takes OTLP metrics, and a
  dashboard shows the pipeline: tick and unit duration, rounds, outcomes, pauses.
- **Nothing sensitive leaves.** Spans and metrics carry identifiers, names and
  counts: unit ids, change names, step names, model names, outcomes. Not prompts,
  diffs, feedback text or commit messages.
