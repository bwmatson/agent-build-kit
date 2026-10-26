## ADDED Requirements

### Requirement: A task group may declare itself independent of the groups before it

A task group SHALL be able to declare, with a reason, that it does not depend on
any earlier group of its change. The unit built from such a group SHALL have no
dependency on the unit before it and SHALL be ready when its change is planned,
subject to its own `Needs` lines. The group following it SHALL depend on the
last unit before the independent group. A `[narrow]` or `[acceptance]` group
SHALL depend on every earlier unit of the change, independent or not. An
independent group SHALL NOT be joined into another unit, and no group SHALL be
joined into its unit. A change with no such declaration SHALL be planned as
before.

#### Scenario: A platform group beside application groups

- **GIVEN** a change of two groups in one repo and a third, declared independent,
  in another
- **WHEN** the change is planned
- **THEN** the third group's unit depends on nothing
- **AND** the second group's unit depends on the first, not on the third

#### Scenario: An acceptance group after an independent group

- **GIVEN** an acceptance group that follows an independent group
- **WHEN** the change is planned
- **THEN** the acceptance unit depends on the independent group's unit as well

#### Scenario: No declaration

- **WHEN** a change without an independence declaration is planned
- **THEN** its units are linked as they were before this requirement

### Requirement: An independence declaration is checked

`abk tags` SHALL reject an independence declaration without a reason, on the
first group of a change, or on a group that is also flagged `[contract]`,
`[narrow]` or `[acceptance]`.

#### Scenario: A declaration without a reason

- **WHEN** a group says `Independent:` and nothing else
- **THEN** `abk tags` reports it

#### Scenario: A declaration on the first group

- **WHEN** group 1 declares itself independent
- **THEN** `abk tags` reports that there is nothing to be independent of
