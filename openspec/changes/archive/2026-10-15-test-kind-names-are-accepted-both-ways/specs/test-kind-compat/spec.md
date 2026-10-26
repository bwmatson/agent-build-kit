## ADDED Requirements

### Requirement: A test kind is one type with the values unit-test and e2e-test

abk SHALL represent the kind of a test as one type whose values are `unit-test` and `e2e-test`, and SHALL use that type for the kind of
a task group, a planned unit and a stored unit. A value that is not one of the two SHALL be refused as it is today, naming the values
that are accepted.

#### Scenario: The values

- **WHEN** the kind of a unit is read
- **THEN** it is `unit-test` or `e2e-test`

#### Scenario: An unknown kind

- **GIVEN** a heading tagged `[integration]`
- **WHEN** the change is read
- **THEN** it is refused, naming `unit-test` and `e2e-test` as the tags accepted

### Requirement: Both spellings of a test kind are read at the edges, the old one with a notice, and the old one is never written

abk SHALL still read the old spellings `tier1` and `tier2` where they exist outside the code: in the tags of a task group heading, in
the keys of an `abk.yaml` (`tier1_*`, `tier2_*`, `tests.tier2_marker`, `tier2_runtimes`, `tier2_splits`), and in the values of the
state files already written. Reading one SHALL give the same meaning as the new spelling and SHALL produce a notice naming the new
spelling, from `abk tags`, `abk check`, `abk config` and `abk doctor`. abk SHALL never write an old spelling. A file that holds an old
and a new spelling of the same setting SHALL be refused, naming both.

#### Scenario: An old tag still validates

- **GIVEN** a change whose headings read `[tier1]` and `[tier2]`
- **WHEN** `abk tags` and `abk check` run
- **THEN** the change validates, each old tag is reported once as deprecated with the tag that replaces it, and the units planned from
  it are the same as under the new tags

#### Scenario: An old setting still loads

- **GIVEN** an `abk.yaml` with `global_limits.tier2_lock_wait_seconds: 600`
- **WHEN** it is loaded
- **THEN** the setting has the value 600 under `e2e_lock_wait_seconds`, `abk config` and `abk doctor` say so, and printing the
  configuration shows only the new key

#### Scenario: Both spellings of one setting

- **GIVEN** an `abk.yaml` holding `tier2_schedule` and `e2e_schedule` under the same block
- **WHEN** it is loaded
- **THEN** loading fails naming both keys and saying to keep one

#### Scenario: Stored values

- **GIVEN** a `units.json` whose units carry `"tier": "tier2"` and a `planned.json` written before the rename
- **WHEN** they are read and a unit is updated
- **THEN** the units read as e2e-test, and the file is written back with `e2e-test` and no old value
