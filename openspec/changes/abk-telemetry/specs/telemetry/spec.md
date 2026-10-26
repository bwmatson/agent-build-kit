## ADDED Requirements

### Requirement: Telemetry is off unless enabled and never affects a run

The pipeline SHALL emit OpenTelemetry traces and metrics only when explicitly
enabled by configuration, and SHALL behave identically with it off. When enabled,
a collector that is slow, unreachable or erroring SHALL NOT delay, fail or alter
any step, tick or unit. Export failures SHALL be reported at most as a warning.
A missing telemetry dependency SHALL be reported once and SHALL NOT stop the
pipeline.

#### Scenario: Telemetry is off

- **WHEN** a tick runs without the switch set
- **THEN** no telemetry library is imported and nothing is exported

#### Scenario: The collector is down

- **GIVEN** telemetry enabled with an endpoint nothing answers on
- **WHEN** a tick builds a unit
- **THEN** the unit is built as it would be with telemetry off
- **AND** at most a warning is logged

#### Scenario: The dependency is missing

- **GIVEN** telemetry enabled without the telemetry extra installed
- **WHEN** a tick runs
- **THEN** one line says the extra is missing and the tick continues

### Requirement: A run is traced from the tick to the agent call

When enabled, the pipeline SHALL emit a span for each tick, each unit run in it,
each step of a unit, and each agent call, nested in that order, with the unit's
identifier, change, repository, step, round, runtime, model and outcome as
attributes. Spans SHALL NOT carry prompts, diffs, feedback or commit messages.
Context SHALL be carried explicitly into worker threads so a unit's spans belong
to its tick's trace. A unit resumed in a later tick SHALL link to its earlier
trace.

#### Scenario: A unit reviewed twice

- **WHEN** a unit takes two review rounds in a tick
- **THEN** its run span has a step span per round, each with an agent span
  below it

#### Scenario: Nothing sensitive is attached

- **WHEN** a unit's rework is driven by a reviewer's comment
- **THEN** no span or metric attribute contains the comment's text

### Requirement: The pipeline's time, rounds and outcomes are measured

When enabled, the pipeline SHALL record metrics for tick, unit and step duration,
review rounds per unit, check failures, agent turns, usage pauses and reclaimed
units, and SHALL record token counts where the runtime reports them. Metric
attributes SHALL be of bounded cardinality: unit identifiers and change names
SHALL NOT be metric attributes.

#### Scenario: A usage pause

- **WHEN** a tick pauses for the usage window
- **THEN** a pause is counted with its kind

#### Scenario: A runtime without token counts

- **GIVEN** a runtime whose output carries no token counts
- **WHEN** it runs an agent step
- **THEN** its turns and duration are recorded and no token series is

### Requirement: Telemetry is flushed before the process exits

A tick SHALL flush pending telemetry before exiting, within a bounded time, so
the short-lived process does not drop what it just recorded.

#### Scenario: A tick ends

- **WHEN** a tick finishes with telemetry enabled
- **THEN** its spans and metrics are exported before the process exits, or the
  flush gives up within its bound
