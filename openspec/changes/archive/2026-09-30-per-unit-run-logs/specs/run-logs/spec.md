# Spec Delta

## Purpose

Defines that each unit's run is written to a file named after that unit, where it lives, how it is
found from the unit's record, and how it is bounded.

## ADDED Requirements

### Requirement: Each unit's run is written to a file named for that unit

The pipeline SHALL write the lines it emits for a unit's run to a file of its own, whose name begins
with the unit's identity — its change and its number, the number padded so units of one change sort
in order — followed by when the run started and which step it was. Every run of one unit SHALL
therefore group together in a listing, and successive runs of that unit SHALL read in order.

#### Scenario: Looking for one unit

- **WHEN** someone lists the log directory
- **THEN** every run of a given unit appears together, ordered by when it ran

#### Scenario: Two-digit units

- **WHEN** a change has ten or more units
- **THEN** unit 2 sorts before unit 10 rather than after it

#### Scenario: Which step it was

- **WHEN** a unit has runs for several steps
- **THEN** each file names its step, so the step is known without opening it

### Requirement: A run's file says what the run was

Each file SHALL open with the unit, its change, the step, the model used, the base the run built on
and the time it started, and SHALL close with how the run ended. Between them it SHALL carry the
lines the pipeline emits for that unit.

#### Scenario: Opening a log cold

- **WHEN** a person opens a run's file having forgotten the context
- **THEN** the unit, step, model and base are stated before the transcript

### Requirement: The unit's record leads to its log

A unit SHALL carry the name of its most recent run's file, so that a person or an agent reading the
unit's record can reach the transcript without searching by time.

#### Scenario: Diagnosing a failure

- **WHEN** a unit has failed and its record is read
- **THEN** the name of the run's file is there

### Requirement: The logs are machine-local and bounded

These files SHALL NOT be versioned, as the per-tick logs beside them are not. The pipeline SHALL
keep only a bounded number of runs per unit, and SHALL remove a change's unit logs when that change
is archived.

#### Scenario: A unit reworked many times

- **WHEN** a unit has been run more times than the bound allows
- **THEN** only the most recent runs are kept

#### Scenario: A change that has been archived

- **WHEN** a change is archived
- **THEN** its units' logs are removed

#### Scenario: Not in version control

- **WHEN** the planning repository's status is read after a run
- **THEN** no run log appears as a change to commit

### Requirement: The journal still receives everything

Writing these files SHALL NOT remove or reduce what the pipeline prints to its own output, so a
pass remains readable in one place, including the lines that belong to no unit.

#### Scenario: A pass with several units

- **WHEN** a pass builds more than one unit
- **THEN** its whole output is still printed as it is today, and each unit's lines are also in that
  unit's file
