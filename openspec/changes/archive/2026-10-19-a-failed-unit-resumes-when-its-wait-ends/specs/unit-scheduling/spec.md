## ADDED Requirements

<!-- `failed-units-waiting-on-a-prerequisite-free-their-slot` states, in its own unarchived delta only, that a waiting failed unit "is never requeued by
the pipeline". The requirement below supersedes that sentence; it is ADDED, not MODIFIED, because the requirement it changes is not in the main spec yet. -->

### Requirement: A failed unit whose wait ends is requeued once

A failed unit that waits on another unit SHALL stay failed while it waits. When its wait ends, that is when the units it waits on are no longer
a wait for it and each has merged, been satisfied with its work landed, or (in the same repository) entered review, the pipeline SHALL requeue it
without a person, as `abk requeue` does, once for that wait. The requeue SHALL keep the unit's thread, branch, saved failure and a person's
guidance, SHALL record in its history that its wait ended and name the prerequisite, SHALL go through the usage check and the slot rules as any resume does, and SHALL NOT be held by the limit on units in
progress. A unit that fails again and waits on nothing new SHALL NOT be requeued again; a prerequisite added later SHALL start a new wait and a new
requeue. A held, merged, closed or satisfied unit, and a failed unit that has not waited, SHALL NOT be requeued by the pipeline.

#### Scenario: The wait ends

- **WHEN** a failed unit waits on a `Needs:` parent and the parent merges
- **THEN** the pipeline requeues the unit once without a person, the unit runs again, and its history says its wait ended and names the parent

#### Scenario: It fails again

- **WHEN** the requeued unit fails again and waits on nothing
- **THEN** it stays failed and the pipeline does not requeue it again

#### Scenario: A new prerequisite

- **WHEN** a second prerequisite is added to the failed unit after the first requeue and later merges
- **THEN** the unit is requeued a second time, once

#### Scenario: A held unit

- **WHEN** a held unit's prerequisite merges
- **THEN** the unit is not requeued

#### Scenario: A plain failure

- **WHEN** a failed unit has never waited on another unit
- **THEN** it stays failed until a person requeues it

#### Scenario: A usage pause

- **WHEN** a failed unit's wait ends during a usage pause
- **THEN** the requeue is delivered and no build starts until the pause ends

#### Scenario: A branch in use

- **WHEN** a failed unit's wait ends while another run holds its branch
- **THEN** the unit stays failed and is requeued on a later pass once the branch is free

### Requirement: The requeue when a wait ends picks its mode from the unit's record

The pipeline SHALL choose the mode of the requeue from what the unit's record holds: a failure whose cause is the environment's (the toolchain,
the environment, an unreachable host, network or service) SHALL be resumed; a saved failure from a tier 1 or tier 2 check with feedback
SHALL be reworked from that failure; any other unit SHALL be resumed; and it SHALL NOT start over. A person's recorded guidance SHALL be kept and
SHALL NOT change the mode. The setting `global_limits.wait_end_requeue` SHALL be `auto` (the default), `resume`, `rework` or `off`; `resume` and `rework` SHALL force
that mode (a rework with no saved failure and no guidance resuming), and `off` SHALL leave a failed unit that waits as it is today, requeued by a person only.

#### Scenario: A check failure on real errors

- **WHEN** the unit's saved failure is a tier 2 check failure with feedback and its wait ends
- **THEN** it is requeued as a rework from that failure

#### Scenario: An environmental failure

- **WHEN** the unit failed for a missing toolchain and its wait ends
- **THEN** it is requeued as a resume

#### Scenario: A person's note

- **WHEN** the unit carries guidance a person recorded and its wait ends
- **THEN** the guidance is kept and the mode is still the one the record gives

#### Scenario: The setting is off

- **WHEN** `global_limits.wait_end_requeue` is `off` and a failed unit's wait ends
- **THEN** the unit stays failed and nothing requeues it

### Requirement: A wait that ended on a closed prerequisite is left to a person

When a failed unit's wait ends and a prerequisite it waited on was closed rather than merged, the pipeline SHALL NOT requeue it. The status SHALL
say that the wait ended, name the closed prerequisite and say that the unit can be requeued. The status SHALL also say how many failed units were resumed today
because their wait ended.

#### Scenario: A prerequisite was closed

- **WHEN** a failed unit's wait ends and the prerequisite is closed
- **THEN** it stays failed and the status says `wait ended: <prerequisite> closed, requeue to retry`

#### Scenario: The count

- **WHEN** two failed units were requeued today because their waits ended
- **THEN** the status says `failed units resumed when their wait ended: 2 today`
