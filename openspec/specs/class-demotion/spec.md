# class-demotion Specification

## Purpose
TBD - created by archiving change low-risk-units-land-without-a-person. Update Purpose after archive.

## Requirements

### Requirement: A demotion is a runtime override that holds a class at `light`

A demotion SHALL be a record in `runs/` naming the class, what triggered it, the unit and the time, and SHALL NOT be written to
abk.yaml. While a class is demoted, the verdict SHALL take it as one more floor holding the class at `light`, and the landing step
SHALL NOT land a unit of the class. A demotion SHALL only ever raise the review a unit gets.

#### Scenario: A demoted class

- **GIVEN** a class that clears every other floor and is demoted
- **WHEN** a unit of the class has its verdict computed
- **THEN** its tier is `light` and the reason names the demotion

#### Scenario: Landing

- **GIVEN** an `auto` unit approved before its class was demoted
- **WHEN** the landing step runs
- **THEN** it does not land

#### Scenario: Policy untouched

- **WHEN** a class is demoted
- **THEN** abk.yaml is unchanged

### Requirement: A revert of an auto-landed unit demotes its class

When the outcome of an auto-landed unit becomes `reverted`, the pipeline SHALL demote the unit's class. The revert of a unit a person
merged SHALL NOT demote anything.

#### Scenario: A revert

- **GIVEN** an auto-landed unit of class `docs`
- **WHEN** its outcome becomes `reverted`
- **THEN** `docs` is demoted with the trigger `revert` and the unit named

#### Scenario: A person's merge

- **GIVEN** a unit a person merged
- **WHEN** its outcome becomes `reverted`
- **THEN** no class is demoted

### Requirement: A verify failure demotes the classes of the change's auto-landed units

When verify for a change is recorded as failed, the pipeline SHALL demote the class of each auto-landed unit of that change. A change
with no auto-landed unit SHALL demote nothing.

#### Scenario: A failure

- **GIVEN** a change with one auto-landed unit of class `docs` and one a person merged
- **WHEN** its verify fails
- **THEN** `docs` is demoted with the trigger `verify`

#### Scenario: No auto-landed unit

- **GIVEN** a change merged only by people
- **WHEN** its verify fails
- **THEN** no class is demoted

### Requirement: A failed audit demotes the class

When an audit is recorded `wrong`, the pipeline SHALL demote the unit's class. An audit recorded `ok` SHALL NOT.

#### Scenario: Wrong

- **WHEN** `abk review audit <unit> wrong` is recorded
- **THEN** the unit's class is demoted with the trigger `audit`

#### Scenario: Ok

- **WHEN** `abk review audit <unit> ok` is recorded
- **THEN** no class is demoted

### Requirement: Agreement below the minimum over the window demotes the class

For a class listed in `auto_land.classes`, when its agreement rate over the most recent `demotion.window` agreement samples falls
below `demotion.min_agreement`, and it has at least the smaller of `window` and `auto_land.min_samples` such samples, the pipeline
SHALL demote it. Only samples with brief-carrying records SHALL count. A class with fewer samples SHALL NOT be demoted by agreement.

#### Scenario: Below

- **GIVEN** `window` 10 and `min_agreement` 0.9 and the last ten agreement samples with eight accepted
- **WHEN** the demotions are evaluated
- **THEN** the class is demoted with the trigger `agreement`

#### Scenario: At the minimum

- **GIVEN** the last ten with nine accepted
- **WHEN** the demotions are evaluated
- **THEN** it is not demoted

#### Scenario: Too few samples

- **GIVEN** a class with three samples, none accepted
- **WHEN** the demotions are evaluated
- **THEN** it is not demoted by agreement

#### Scenario: Samples without the brief

- **GIVEN** a class whose records have no brief
- **WHEN** the demotions are evaluated
- **THEN** none of them counts

### Requirement: Only a person lifts a demotion

`abk review reinstate <class>` SHALL lift a class's demotion, recording the time, and units whose verdict is computed afterwards
SHALL no longer be held by it. Nothing else SHALL lift a demotion, and time passing or good results SHALL NOT. The command SHALL be
refused for a class that is not demoted. A second trigger on a class already demoted SHALL be added to its record and logged and
SHALL NOT create a second demotion.

#### Scenario: Reinstated

- **GIVEN** a demoted class
- **WHEN** a person runs `abk review reinstate docs`
- **THEN** the demotion is marked lifted with the time and a later verdict is not held by it

#### Scenario: Not demoted

- **WHEN** the command names a class that is not demoted
- **THEN** it is refused and nothing changes

#### Scenario: Time passes

- **GIVEN** a demotion a month old and no command
- **WHEN** a verdict is computed
- **THEN** the class is still held at `light`

#### Scenario: A second trigger

- **GIVEN** a demoted class
- **WHEN** an audit is recorded `wrong` for it
- **THEN** the existing demotion gains the trigger and there is still one demotion

### Requirement: Every demotion and lift is logged and notified, and status shows what is demoted

Every demotion and every lift SHALL be written to the run log and SHALL raise a card: one while the demotion stands, and a notice of
the lift for 24 hours with no reminder. `abk status` SHALL list each demoted class with its trigger, the unit and since when.

#### Scenario: A demotion

- **WHEN** a class is demoted
- **THEN** a log line names it and the trigger, and a card is raised that stays until it is lifted

#### Scenario: A lift

- **WHEN** a demotion is lifted
- **THEN** a log line records it, the demotion card is cleared and a notice of the lift is shown once

#### Scenario: Status

- **GIVEN** a demoted class
- **WHEN** `abk status` runs
- **THEN** it lists the class with its trigger and since when
