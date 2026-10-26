## ADDED Requirements

### Requirement: A recorded plan carries the sizing configuration it was made under

When a change's plan is recorded, the record SHALL carry a digest of the sizing configuration: the `review` section, the floor and
`max_unit_lines`. The digest SHALL be empty when `review.enabled` is false. A record with no digest SHALL read as an empty one.

#### Scenario: Recorded with the plan

- **GIVEN** `review.enabled` true
- **WHEN** a change is planned
- **THEN** its record holds the current digest

#### Scenario: Flag off

- **GIVEN** `review.enabled` false
- **WHEN** a change is planned
- **THEN** its record holds an empty digest

#### Scenario: A record from before

- **WHEN** a record written before the digest existed is read
- **THEN** its digest reads as empty

### Requirement: A plan made under other sizing is stale

A change's plan SHALL be stale when the digest its record holds is not the current one. A change of a ceiling, of the floor, of a repo's
`review` block or of `review.enabled` SHALL make every plan recorded under the other values stale, and an installation that has never
enabled review SHALL have no stale plan.

#### Scenario: The flag is turned on

- **GIVEN** plans recorded with `review.enabled` false
- **WHEN** it is turned on
- **THEN** every recorded plan is stale

#### Scenario: A ceiling changes

- **GIVEN** plans recorded with `review.enabled` true and `light: 2000`
- **WHEN** `light` is set to 2500
- **THEN** every recorded plan is stale

#### Scenario: Never enabled

- **GIVEN** an installation whose plans have no digest and `review.enabled` false
- **WHEN** staleness is read
- **THEN** no plan is stale

### Requirement: A stale plan is reported and not replanned until a person asks

A tick SHALL NOT plan a change again because its plan is stale, SHALL NOT count a stale plan as work to do, and SHALL report the stale
changes by name with the way to plan them. `abk replan` with no argument SHALL list each stale plan as stale, `abk status` SHALL say how
many there are, and `abk replan` naming a change SHALL plan it and record the current digest.

#### Scenario: The tick

- **GIVEN** a change with a current `tasks.md` hash and a stale plan
- **WHEN** a tick runs
- **THEN** the planner is not called for it, the tick says the plan is stale and names `abk replan`, and an otherwise idle tick has no work

#### Scenario: The listing

- **WHEN** `abk replan` is run with no argument
- **THEN** a stale change's line says it is stale, and a current one's does not

#### Scenario: Planned again by name

- **WHEN** `abk replan` names a stale change and the plan succeeds
- **THEN** its record holds the current digest and the change is no longer listed as stale

#### Scenario: A change of `tasks.md`

- **GIVEN** a stale plan whose `tasks.md` has been edited
- **WHEN** a tick runs
- **THEN** the change is planned as it always is, and its record holds the current digest
