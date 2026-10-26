## ADDED Requirements

### Requirement: The status shows who holds the tier 2 lock

`abk status` SHALL show, when the tier 2 lock is held, the unit that holds it and how long it has held it. A record of a holder whose process is gone,
while the lock is free, SHALL be shown as stale and not as a holder; a lock that is held while its recorded process is gone SHALL be shown as held
and say so. When the lock is free and has no record, the status SHALL show no tier 2 line. Reading the status SHALL NOT leave the lock held or change
its file.

#### Scenario: A held lock

- **GIVEN** a unit holding the tier 2 lock since forty minutes ago
- **WHEN** `abk status` is run
- **THEN** it shows that unit as the holder and an age of forty minutes

#### Scenario: A stale record

- **GIVEN** a free lock whose record names a process that is gone
- **WHEN** `abk status` is run
- **THEN** the record is shown as stale, not as a holder, and the file is unchanged

#### Scenario: A free lock

- **GIVEN** a free lock with no record
- **WHEN** `abk status` is run
- **THEN** no tier 2 line is shown

#### Scenario: A held lock whose recorded process is gone

- **GIVEN** a held lock whose record names a process that is gone
- **WHEN** `abk status` is run
- **THEN** it shows the lock as held and says the recorded process is gone

#### Scenario: Reading the status leaves the lock alone

- **GIVEN** a free lock
- **WHEN** `abk status` is run and a unit then asks for the lock
- **THEN** the unit gets it at once
