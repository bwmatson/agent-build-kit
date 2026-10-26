# Spec Delta

## Purpose

Defines what a pull request's labels say about its unit: the state the pipeline
maintains, the instructions a person gives, and which of those is consumed.

## ADDED Requirements

### Requirement: A pull request carries its unit's state as a label

The pipeline SHALL maintain one label on each of its pull requests naming the
unit's current state, and SHALL replace it when the state changes so that exactly
one such label is present at a time. States with no pull request, and states the
host already shows on a pull request, SHALL NOT have labels.

#### Scenario: A unit moves through its states

- **WHEN** a unit starts building, reaches review, is sent back for rework, and is
  then held
- **THEN** its pull request carries exactly one state label at each point, naming
  that state, with the previous one removed

#### Scenario: A state the host already shows

- **WHEN** a unit merges or its pull request is closed
- **THEN** no state label is added for it

### Requirement: The labels and the unit graph share one vocabulary

The state names and the colours used for labels SHALL be the same ones the unit
graph uses, held in one definition that both the graph and the labels read, so
neither can be renamed or recoloured without the other following. That vocabulary
SHALL include the states the graph derives from a unit's history — waiting on a
dependency, stopped before a rework, stopped for a spent usage window — and not only
the states the unit store records, because those distinctions are what tell a
reader why a unit is not moving.

Where a host renders a label as a single colour, the colour used SHALL be the one
the graph draws a state's outline with, not the pale fill it shades the node with.

#### Scenario: A state the graph can draw

- **WHEN** the graph can draw a state
- **THEN** either a label of the same name and colour exists for it, or it is one of
  the documented states deliberately left unlabelled

#### Scenario: A state is renamed or recoloured

- **WHEN** a state's name or colour changes in the shared vocabulary
- **THEN** both the graph and the labels change with it, with nothing to update
  twice

#### Scenario: Why a unit is not moving

- **WHEN** a unit is waiting on a dependency, stopped before a rework, or stopped
  because a usage window is spent
- **THEN** its label says which, rather than all three reading the same

### Requirement: What a person writes is told apart from what the pipeline writes

The labels a person adds to instruct the pipeline SHALL be distinguishable by name
from the labels the pipeline maintains, and the pipeline SHALL NOT treat a label it
wrote as an instruction.

#### Scenario: The pipeline labels a pull request

- **WHEN** the pipeline sets or replaces a state label
- **THEN** no rework, hold or other dispatch follows from that label appearing

### Requirement: An instruction to rework is consumed when it is acted on

When the pipeline dispatches a rework because a person asked for one with a label,
it SHALL remove that label, so that the pull request reflects its state rather than
an outstanding request, and so that the same instruction can be given again.

#### Scenario: A rework is requested and dispatched

- **WHEN** a person adds the rework label and the pipeline sends the unit back
- **THEN** the label is removed, and the pull request instead carries the state
  label for being reworked

#### Scenario: Asking twice

- **WHEN** a person adds the rework label again after an earlier one was consumed
- **THEN** a new rework is dispatched

#### Scenario: A hold is not consumed

- **WHEN** a person adds the hold label
- **THEN** it remains until a person removes it, because it withdraws the unit for
  as long as it is present rather than requesting a single action

### Requirement: Labelling is cosmetic and never costs a unit

A label the repository lacks SHALL be created once, with a description of what it
means. A failure to read, create, set or remove any label SHALL be logged once and
otherwise ignored: it SHALL NOT fail, hold or delay a unit, and no decision SHALL
be made by reading a state label back — the unit store remains the source of truth.

#### Scenario: A repository without the labels

- **WHEN** the pipeline first labels a pull request in a repository that has none
  of these labels
- **THEN** they are created with their descriptions and applied

#### Scenario: The host refuses

- **WHEN** a label call fails for any reason
- **THEN** the unit proceeds exactly as it would have, and the failure is logged
  once

#### Scenario: Nothing reads it back

- **WHEN** the pipeline decides what to do with a unit
- **THEN** it reads the unit store, not the pull request's state label
