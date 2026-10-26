# Spec Delta

## Purpose

Defines what happens when a step ends having written nothing while the account's usage
is exhausted: the unit is paused in the existing shape, not failed.

## ADDED Requirements

### Requirement: An empty step is judged against the usage window before it fails

When a step ends having produced nothing, the pipeline SHALL consult the usage reading
it already holds, and where the account's window is exhausted SHALL leave the unit in
the same state, with the same note wording and the same record of where to continue, as
a unit stopped between steps for that reason — not as a failure. The reading SHALL be
one the pipeline already has rather than a new call, and no usage SHALL be read while a
step is running.

#### Scenario: A quiet refusal

- **WHEN** a step ends having written nothing and the usage window is exhausted
- **THEN** the unit is paused, recorded as a stop between steps is recorded, and set to
  continue at that step

#### Scenario: Shown as a pause

- **WHEN** such a unit is drawn on the unit graph
- **THEN** it appears as stopped for usage rather than failed

#### Scenario: An empty step with usage to spare

- **WHEN** a step ends having written nothing and the window is healthy
- **THEN** this requirement does not apply and the outcome is decided elsewhere

### Requirement: Running steps are still never interrupted

The pipeline SHALL NOT stop, kill or re-check a step that is already running on account
of usage. Usage SHALL continue to be checked only when deciding whether to begin a step.

#### Scenario: The window fills during a long step

- **WHEN** the window crosses its threshold while a step is running
- **THEN** that step runs to completion, and only the next step's start is gated

### Requirement: A paused unit resumes through the mechanism that exists

A unit paused this way SHALL be picked up by the resume the pause already schedules,
keeping its branch, its commits and any feedback, and SHALL resume at the step that did
not finish — with no recovery mechanism added for it.

#### Scenario: After the window resets

- **WHEN** the scheduled resume runs
- **THEN** the unit may be built in that pass and continues at the step it stopped in,
  with its earlier commits intact
