## ADDED Requirements

### Requirement: A unit's state changes record why, as a defined cause

Every change of a unit's state out of running SHALL record a cause from a fixed set
alongside any explanatory text, and the scheduler, the readmission rule and the diagram
SHALL decide from the cause, never from the wording of the text. The framework SHALL NOT
derive a cause from a note; a state change recorded before causes existed SHALL have no
cause and SHALL NOT be readmitted by a running pass.

#### Scenario: A hold for a moved base, in the graph engine's words

- **GIVEN** a unit held with a note that begins "base moved before its push"
- **WHEN** the running pass looks for units sent back since it started them
- **THEN** the unit is let back in because its cause is a moved base

#### Scenario: A hold for another reason

- **GIVEN** a unit held for a toolchain it cannot build
- **WHEN** the running pass looks for units sent back
- **THEN** it is not let back in, and the log says why

#### Scenario: A note is reworded

- **WHEN** the text of a note changes and its cause does not
- **THEN** no scheduling decision changes

#### Scenario: A record from before causes

- **GIVEN** a history entry with only a note, written before causes existed
- **WHEN** the running pass looks for units sent back
- **THEN** it has no cause and is not readmitted
- **AND** no code reads its note to decide

### Requirement: Events carry their kind

Events delivered to a unit SHALL carry a kind from a fixed set (the requeue reason, the
rework kind) beside any display text, and the handling of the event SHALL depend on the
kind. Feedback SHALL record its source, and the prompt chosen for it SHALL depend on the
source.

#### Scenario: A failing check sends a unit back

- **WHEN** the poller reports newly failing checks
- **THEN** the rework gets the CI log only, chosen by the event's kind

#### Scenario: Feedback that starts like a check failure

- **GIVEN** a reviewer's feedback whose text begins "tier 1 failed:"
- **WHEN** it is saved and used
- **THEN** it is treated as review feedback, because its source says so

### Requirement: A unit's outcome and a usage pause are defined values

The outcome of a unit run SHALL be one of a fixed set shared by the graph, the CLI and
telemetry, and a usage pause SHALL carry its reason and resume time as fields, not as
the outcome's detail text. An unsupported toolchain SHALL be reported by its own
exception, and no other failure SHALL be classified as one.

#### Scenario: A usage pause

- **WHEN** a run pauses for the usage window
- **THEN** the pause's reason and resume time come from its fields

#### Scenario: A failure that is not the toolchain

- **WHEN** a run raises an unrelated `NotImplementedError`
- **THEN** it is not held as a toolchain problem
