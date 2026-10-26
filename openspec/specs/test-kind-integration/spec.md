# test-kind-integration Specification

## Purpose
TBD - created by archiving change integration-test-kind-is-a-label. Update Purpose after archive.

## Requirements

### Requirement: integration-test is a third test-kind tag, read wherever a kind is read

abk SHALL accept `[integration-test]` as a group-heading tag beside `[unit-test]` and `[e2e-test]`, and SHALL accept the value
`integration-test` as the kind of a planned unit and of a stored unit. `abk tags`, `abk status` and the planner's plan validation SHALL
show and accept it as a kind of its own, and every message that lists the tags accepted SHALL list all three. `[integration]` without
`-test`, and `tier3`, SHALL still be refused, naming the three tags. `[acceptance]` SHALL still be accepted only on an `e2e-test` group.

#### Scenario: The tag is read

- **GIVEN** a `tasks.md` whose headings read `## 1. [app] [unit-test] A`, `## 2. [app] [integration-test] B` and `## 3. [app] [e2e-test] C`
- **WHEN** `abk tags` and `abk check` read the change
- **THEN** all three are accepted, `abk tags` lists `[unit-test]`, `[integration-test]` and `[e2e-test]` without a notice, and the kinds of
  the groups are the three `TestTier` members in that order
- *Test level: unit.*

#### Scenario: A near miss is still refused

- **GIVEN** headings tagged `[integration]` and `[tier3]`
- **WHEN** the change is read
- **THEN** each is refused, and the message names `unit-test`, `integration-test` and `e2e-test` as the tags accepted
- *Test level: unit.*

#### Scenario: Acceptance stays e2e-test

- **GIVEN** a group headed `## 2. [app] [integration-test] [acceptance] Drive it`
- **WHEN** the change is read
- **THEN** it is refused because `[acceptance]` needs `[e2e-test]`
- *Test level: unit.*

#### Scenario: A plan and a store hold the kind

- **GIVEN** a planner reply with a unit whose `tier` is `integration-test`, and a stored unit of that kind
- **WHEN** the reply is parsed and the store is written and read back
- **THEN** the unit's kind is `integration-test` in both, and a `tier` that is not one of the three is refused as before
- *Test level: unit.*

#### Scenario: Status shows the kind

- **GIVEN** a stored unit of the `integration-test` kind
- **WHEN** `abk status` prints it
- **THEN** its kind is shown as `integration-test`, and it appears in none of the lists meant for `e2e-test` units
- *Test level: unit.*

### Requirement: integration-test is a label that behaves as unit-test

A unit of the `integration-test` kind SHALL be built, checked and verified exactly as a unit of the `unit-test` kind: the same unit-test
command and checks, no e2e lock taken, no `local/e2e-test` status posted, no place in the scheduled e2e run, and no appearance in a list
or setting that is for `e2e-test` units alone. abk SHALL have no setting named for `integration-test`; the `unit_test_*` settings apply. The
kind SHALL NOT select or imply the pytest `integration` marker or `tests/integration/`, and abk's documents SHALL say so.

#### Scenario: No stack is taken

- **GIVEN** a unit of the `integration-test` kind that passes its unit-test checks
- **WHEN** it is verified and its result is posted
- **THEN** no e2e lock is taken, no e2e run is started, and no `local/e2e-test` status is posted
- *Test level: unit.*

#### Scenario: The unit-test settings apply

- **GIVEN** a workspace with `unit_test_command_seconds` set
- **WHEN** a unit of the `integration-test` kind runs its command
- **THEN** the limit is the one set, and no setting named for `integration-test` exists
- *Test level: unit.*

#### Scenario: The scheduled e2e run leaves it out

- **GIVEN** a store holding units of all three kinds
- **WHEN** the scheduled e2e run decides which repositories to run
- **THEN** only repositories with an `e2e-test` unit are chosen
- *Test level: unit.*

#### Scenario: The marker is not implied

- **GIVEN** the documents abk ships
- **WHEN** they describe the kinds
- **THEN** they say `integration-test` covers behaviour across modules or files in the ordinary suite with no live stack, and say it is not the
  pytest `integration` marker or `tests/integration/`
- *Test level: unit — a documents test over the shipped Markdown, extended by the rename change's documents groups.*

### Requirement: A unit takes the widest kind among its groups

The kinds SHALL be ordered by width, `unit-test` then `integration-test` then `e2e-test`. A unit built from several groups SHALL take the
widest kind among them. When a join gives a unit the groups of another, the surviving unit SHALL take the widest of both. A check of a
started unit's tags against its stored kind SHALL compare with the widest kind among the groups it carries, not with each group.

#### Scenario: A mix of unit-test and integration-test

- **GIVEN** a change whose groups 1 and 2 are tagged `[unit-test]` and `[integration-test]` and that the planner builds as one unit
- **WHEN** the unit is planned
- **THEN** its kind is `integration-test`
- *Test level: unit.*

#### Scenario: Any e2e-test group

- **GIVEN** a unit of groups tagged `[unit-test]`, `[integration-test]` and `[e2e-test]`
- **WHEN** it is planned
- **THEN** its kind is `e2e-test`
- *Test level: unit.*

#### Scenario: One kind alone

- **GIVEN** a unit whose groups are all `[unit-test]`, and another whose groups are all `[integration-test]`
- **WHEN** they are planned
- **THEN** their kinds are `unit-test` and `integration-test`
- *Test level: unit.*

#### Scenario: The tag check agrees with the unit

- **GIVEN** a started unit of kind `integration-test` that carries a `[unit-test]` group and an `[integration-test]` group
- **WHEN** `abk replan` checks the stored kind against the tags
- **THEN** no difference is reported; and when the `[integration-test]` group is retagged `[unit-test]`, a difference is reported naming the unit
- *Test level: unit.*

### Requirement: unit-test and integration-test may be joined, e2e-test never

The check of a join SHALL accept two units, or a group and a unit, in the same repository and project whose kinds are both `e2e-test` or
neither, and SHALL refuse one `e2e-test` and one not. The planner's prompt SHALL say the pair must be in the same repository and of
compatible kinds (`unit-test` and `integration-test` together, `e2e-test` only with `e2e-test`), and its schema example SHALL list the
kind as `unit-test|integration-test|e2e-test`.

#### Scenario: A unit-test group onto an integration-test unit

- **GIVEN** an unstarted unit of kind `integration-test` and a group tagged `[unit-test]` in the same repository and project, in a straight line
- **WHEN** the planner joins the group onto the unit
- **THEN** the join is accepted and the surviving unit's kind is `integration-test`
- *Test level: unit.*

#### Scenario: An integration-test group onto a unit-test unit

- **GIVEN** an unstarted unit of kind `unit-test` and a group tagged `[integration-test]`
- **WHEN** the planner joins the group onto the unit
- **THEN** the join is accepted and the surviving unit's kind is `integration-test`
- *Test level: unit.*

#### Scenario: An e2e-test never joins the others

- **GIVEN** an unstarted `e2e-test` unit and a group or a unit of kind `unit-test` or `integration-test`
- **WHEN** a join between them is checked, in either direction
- **THEN** it is refused, naming the repository or kind that differs
- *Test level: unit.*

#### Scenario: The prompt says it

- **WHEN** the planner's prompt is built
- **THEN** the join rule names compatible kinds rather than the same tier, and the reply schema shows `unit-test|integration-test|e2e-test`
- *Test level: unit.*

### Requirement: Calibration pools integration-test with unit-test

The calibration of a unit's size SHALL key a ratio by repository, kind and flag with `integration-test` counted as `unit-test`, so that a
unit of either kind is calibrated by the samples of both and no ratio starts from nothing for the new label. This SHALL hold for a stored
unit's kind, a planned unit's kind and the join ceiling check.

#### Scenario: One kind of sample

- **GIVEN** merged units of the `unit-test` kind and of the `integration-test` kind in one repository with the same flag
- **WHEN** the calibration is computed
- **THEN** it holds one ratio for that repository and flag, built from both sets of samples
- *Test level: unit.*

#### Scenario: A new unit is calibrated by it

- **GIVEN** that ratio and a planned unit of the `integration-test` kind
- **WHEN** the plan is checked against the ceiling
- **THEN** the unit's estimate is multiplied by that ratio, as for the same unit tagged `unit-test`
- *Test level: unit.*

#### Scenario: A join is checked by it

- **GIVEN** two units, one of each kind, in a straight line
- **WHEN** their join is checked against the ceiling
- **THEN** the same ratio applies to the sum as to a join of two `unit-test` units
- *Test level: unit.*
