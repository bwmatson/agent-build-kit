## ADDED Requirements

### Requirement: A change that cannot be archived does not stop the tick

When archiving a finished change fails, or the change has no directory, the pipeline SHALL
log the change and the reason at warning level, and continue with the other changes and with
scheduling, and the tick SHALL still complete. A change whose archive failed SHALL be tried
again on the next tick. A finished change with no directory SHALL be logged as withdrawn and
skipped without calling the archive command.

#### Scenario: A change with no files

- **GIVEN** a change whose units are all finished and whose directory no longer exists
- **WHEN** a tick runs
- **THEN** it logs the change as withdrawn, archives the others, and builds ready units

#### Scenario: The archive command fails

- **WHEN** archiving one change raises
- **THEN** the other changes are still archived and the tick exits successfully

#### Scenario: Retried on the next tick

- **GIVEN** a change whose archive failed
- **WHEN** the next tick runs
- **THEN** the archive command is called for it again, and a failure is logged again

#### Scenario: A verified change that is not archived

- **GIVEN** a change whose verification passes but whose archive fails or is skipped
- **WHEN** `abk verify <change>` runs
- **THEN** it prints that the change was verified but not archived, with the reason, and exits 1
