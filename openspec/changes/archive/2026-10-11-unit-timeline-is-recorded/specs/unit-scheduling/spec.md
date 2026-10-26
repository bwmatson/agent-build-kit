## ADDED Requirements

### Requirement: Every unit that is not running has one defined wait reason

The pipeline SHALL assign each unit that is not running exactly one reason from a defined set (`WaitReason`, a string enumeration): blocked, queue full, slot, usage pause, lease, backoff, waiting for review, needs a person, or ready. Computing reasons SHALL NOT change which units a pass starts. The values `slot` and `usage_pause` SHALL equal the wait buckets already in the ledger.

#### Scenario: Each cause gets its reason

- **WHEN** units are blocked on a prerequisite, held back by the limit on units in progress, ready but without a free build slot, paused for usage, leased to a person, in backoff, in review, held for a person, or startable
- **THEN** each has the one matching reason

#### Scenario: Starting is unchanged

- **WHEN** reasons are computed for a pass
- **THEN** the units it starts are those it started without them

### Requirement: A change of wait reason is logged once

The pipeline SHALL append `{at, unit, reason, waits_on, tick}` to a decision log in its state directory only when a unit's reason or what it waits on changes, and a closing record when the wait ends. It SHALL resume from the log's tail after a restart. A failing write SHALL be reported once and SHALL NOT fail a pass.

#### Scenario: Nothing changes

- **WHEN** a unit stays blocked on the same unit over many ticks
- **THEN** one record exists for it

#### Scenario: A restart

- **WHEN** the pipeline restarts while a unit's reason is unchanged
- **THEN** no record is repeated

#### Scenario: The reason changes

- **WHEN** a blocked unit's prerequisite merges and no slot is free
- **THEN** a record with the new reason is appended

### Requirement: A unit records when it became ready and when a person first answered

A unit's record SHALL carry `ready_at`, set the first time it is evaluated with nothing blocking it and never reset, and `first_human_activity_at`, set by the first poll that finds a comment or review on its pull request that is not one of the pipeline's own posts. When the unit began and when it entered review SHALL be read from its state history. A unit without these fields SHALL read as it did before.

A new field on a stored unit SHALL default to empty, SHALL be omitted from the written record while it holds its default, and SHALL be handled by an older release as the store already handles unknown keys: dropped when empty, refused with the unit, field and value named when it holds a value. The change that adds it SHALL say so in the changelog.

#### Scenario: Ready once

- **WHEN** a unit becomes ready, waits for a slot, is reworked and is ready again
- **THEN** `ready_at` is the first time

#### Scenario: Own posts are ignored

- **WHEN** the pipeline replies on a pull request and no one else has
- **THEN** `first_human_activity_at` stays unset

#### Scenario: An older record

- **WHEN** a record without the fields is read
- **THEN** they are absent, not zero, and the unit behaves as before

#### Scenario: An older release meets a set field

- **WHEN** an older release reads a record where `ready_at` holds a value
- **THEN** it refuses the record naming the unit, the field and the value

### Requirement: The running pass samples its slots

Each time a running pass refreshes, it SHALL append one `sample` row to the ledger with the counts of units running, in review, blocked and queued, the free workers, the limit and the cap, and SHALL set gauges for free slots and for idle slots with ready work, with no unit or change attribute. A reader that does not know the row kind SHALL skip it.

#### Scenario: One refresh

- **WHEN** a pass refreshes
- **THEN** exactly one sample row is written with those counts

#### Scenario: An unknown kind

- **WHEN** the report reads a ledger holding sample rows
- **THEN** its figures are unchanged
