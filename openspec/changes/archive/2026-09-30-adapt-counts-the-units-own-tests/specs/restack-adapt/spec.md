# Spec Delta

## Purpose

Defines which tests count as a unit's own when the adapt step asks it to account for them.

## ADDED Requirements

### Requirement: A unit's tests are those its changes defined or touched

The tests a unit is asked to account for SHALL be those whose definition its own changes added or
removed, together with those whose body its changes edited. A test that appears in the unit's diff
only as surrounding context SHALL NOT count as the unit's.

#### Scenario: A test the unit wrote

- **WHEN** the unit's changes add a test definition
- **THEN** that test is among the ones it must account for

#### Scenario: A test the unit deleted

- **WHEN** the unit's changes remove a test definition
- **THEN** it is still among them, because a deletion is what the accounting exists to catch

#### Scenario: A test the unit weakened

- **WHEN** the unit's changes edit a line inside a test it did not define
- **THEN** that test is among them, because weakening another's test carries the same risk

#### Scenario: A test that merely sits nearby

- **WHEN** a test definition appears in the unit's diff only on a context line
- **THEN** it is not among them, and no decision is required for it

### Requirement: The accounting names what is outstanding

When the accounting is not satisfied, the problems recorded SHALL name the tests still
outstanding, so that an operator reading a failed unit sees which tests are in question.

#### Scenario: A failed accounting

- **WHEN** a unit fails for an incomplete accounting
- **THEN** its record names the outstanding tests rather than only that something was missing
