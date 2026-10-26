## ADDED Requirements

### Requirement: Nothing carries a unit from the old engine

The framework SHALL NOT contain code that converts a unit from the old engine onto a thread, and
the unit store SHALL NOT accept the old engine's fields. A units store that carries any of them
SHALL fail to load with an error naming the unit and the field and telling the operator to finish
or requeue the old work first.

#### Scenario: A store with an old field

- **GIVEN** a units store in which a unit has the old engine's `review_rounds`
- **WHEN** the store is loaded
- **THEN** loading fails naming the unit and the field

#### Scenario: A tick

- **WHEN** a tick runs
- **THEN** it performs no conversion and logs none

### Requirement: A unit with no recorded cause is simply not readmitted

A unit whose history records no cause SHALL NOT be readmitted by a running pass, and the framework
SHALL NOT log or document special handling for such units beyond listing them in the status.

#### Scenario: A unit from before causes

- **GIVEN** a planned unit whose history has no cause
- **WHEN** a running pass looks for units sent back
- **THEN** it is not readmitted and nothing is logged about it
