## ADDED Requirements

### Requirement: Waiting for the tier 2 lock is never a failure of the unit

Tier 2 runs SHALL be serialized behind one lock. A unit whose tier 2 step finds the lock held SHALL wait until it is free, with no deadline, and SHALL
NOT fail for having waited, whatever the holder's run takes. A caller that chooses a wait of its own, such as verification after a merge, SHALL keep it
and SHALL report the lock as busy when it ends.

#### Scenario: A unit queued behind a long run

- **GIVEN** another unit holds the tier 2 lock for longer than an hour
- **WHEN** a unit's tier 2 step finds it held
- **THEN** the unit keeps waiting, runs its tests when the lock is free, and is not failed

#### Scenario: A free lock

- **GIVEN** no unit holds the lock
- **WHEN** a unit's tier 2 step starts
- **THEN** it runs at once and no wait is logged or recorded

#### Scenario: A caller with its own wait

- **GIVEN** a caller that passes a wait and a lock held for longer than that wait
- **WHEN** the wait ends
- **THEN** the lock is reported busy to that caller and nothing else changes

### Requirement: A wait for the tier 2 lock is visible

While a unit waits for the tier 2 lock the pipeline SHALL log, when the wait begins and at a fixed interval after, that it is waiting, the unit that
holds the lock and for how long it has held it. When the wait ends it SHALL record a ledger span whose `waited` is `tier2_lock` and whose length is the
wait, for the unit; a lock taken without waiting SHALL record none.

#### Scenario: The wait is logged

- **GIVEN** a unit waiting for a lock held by another unit
- **WHEN** the wait begins and again after each interval
- **THEN** the log names the holder and how long it has held the lock

#### Scenario: The wait is a span

- **GIVEN** a unit that waited for the lock and then ran
- **WHEN** its tier 2 step ends the wait
- **THEN** one span with `waited` of `tier2_lock` and the length of the wait is in the ledger for the unit

#### Scenario: No wait, no span

- **GIVEN** a unit that took the lock at once
- **WHEN** its tier 2 step runs
- **THEN** no `tier2_lock` span is recorded

### Requirement: The tier 2 lock names its holder and survives a dead one

The holder of the tier 2 lock SHALL record its unit, process and start time in the lock's file and clear the record when it lets go, including when
its run raises. A record that names a process that is no longer alive, while the lock is free, SHALL be treated as stale: reported, overwritten by the
next holder and not waited for. A lock that is still held SHALL NOT be broken because the recorded process is gone: the wait continues and the
situation is reported.

#### Scenario: The holder is recorded and cleared

- **GIVEN** a unit that takes the lock
- **WHEN** it is held, and again after it is released or its run raises
- **THEN** the record names the unit, process and start time while held, and is empty after

#### Scenario: A stale record

- **GIVEN** a free lock whose record names a process that is gone
- **WHEN** a unit takes the lock
- **THEN** the stale record is reported, replaced by the unit's own, and the unit did not wait

#### Scenario: A held lock whose recorded process is gone

- **GIVEN** a lock that is held while its record names a process that is gone
- **WHEN** a unit waits for it
- **THEN** the lock is not broken, the unit keeps waiting, and the log says the holder's process is gone
