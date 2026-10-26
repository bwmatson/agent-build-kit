## MODIFIED Requirements

### Requirement: A unit's state changes record why, as a defined cause

Every change of a unit's state out of running SHALL record a cause from a fixed set
alongside any explanatory text, and the scheduler, the readmission rule and the diagram
SHALL decide from the cause, never from the wording of the text. The framework SHALL NOT
derive a cause from a note; a state change recorded before causes existed SHALL have no
cause and SHALL NOT be readmitted by a running pass. Causes SHALL be of two kinds, named in
code as two sets that together are exactly the defined causes. A standing cause lasts as long
as the situation it names (`split_held`, `gated`, `upstream_went_back`, `base_changed`,
`restack_deferred`, `restack_conflict`, `restack_handed_back`, `host_unavailable`,
`network_unavailable`, `service_unavailable`, `environment`, `rework`, `usage`,
`dirty_worktree`, `attached`, `needs_human`, `reviewer_hold`, `toolchain`, `depth`,
`review_escalated_class` and `review_escalated_disagreement`) and SHALL stay the unit's cause
until a state change passes another cause or an event cause. An event cause describes a
transition that has happened (`requeued`, `released`, `adopted`, `merged`, `auto_landed`,
`closed` and `failed`) and ends a standing cause when it is recorded.

#### Scenario: A hold for a moved base, in the graph engine's words

- **GIVEN** a unit held with a note that begins "base moved before its push"
- **WHEN** the running pass looks for units sent back since it started them
- **THEN** the unit is let back in because its cause is a moved base

#### Scenario: A hold for another reason

- **GIVEN** a unit held for a toolchain it cannot build
- **WHEN** the running pass looks for units sent back
- **THEN** it is not let back in, and the log says why

#### Scenario: A note is reworded

- **WHEN** the text of a note changes and its cause does not
- **THEN** no scheduling decision changes

#### Scenario: A record from before causes

- **GIVEN** a history entry with only a note, written before causes existed
- **WHEN** the running pass looks for units sent back
- **THEN** it has no cause and is not readmitted
- **AND** no code reads its note to decide

#### Scenario: A standing cause is ended by an event

- **GIVEN** a planned unit whose cause is `gated`
- **WHEN** its requeue is delivered and recorded with the cause `requeued`
- **THEN** its cause is `requeued`, an event cause, and no later change brings `gated` back

#### Scenario: A new cause must be classified

- **WHEN** a cause is added to the defined set
- **THEN** a test fails until it is named as standing or as an event

## ADDED Requirements

### Requirement: A change the store makes on its own account keeps a standing cause

A state change the unit store makes on its own account (a replan demoting a planned unit the plan omits to `unplanned` or promoting an `unplanned` unit back to `planned`, marking a unit `unplanned` because its change vanished, and a join onto a unit) SHALL carry the unit's standing cause forward: the new history entry SHALL record the same cause and the previous entry's note, unless a note is given, and SHALL be marked as carried. It SHALL carry no cause when the unit's cause is an event cause or none, because the transition it described is over. A state change a caller records SHALL still record the cause the caller passes, or none when it passes none, so that a caller ends a standing cause by passing another one or none. A carry SHALL only append: a unit's history SHALL NOT become shorter or lose an entry. A carry SHALL be neither a parking nor a failure: it SHALL NOT count toward `parked_attempts` and SHALL NOT drop the step a parked unit resumes at. No new field SHALL be stored for it, and a units file written by this release SHALL load in the previous release, which reads the carried cause as the latest cause.

#### Scenario: A replan demotes and promotes a parked unit

- **GIVEN** a planned unit with a branch and the cause `split_held`
- **WHEN** a replan omits it and a later replan includes it again
- **THEN** its history has two more entries, both marked as carried with the cause `split_held` and the first entry's note, and its cause reads `split_held`

#### Scenario: A change whose plan vanished

- **GIVEN** an unstarted planned unit with the cause `base_changed` whose change no longer exists
- **WHEN** the vanished change's units are marked `unplanned`
- **THEN** the unit is `unplanned` and its cause still reads `base_changed`

#### Scenario: A join

- **GIVEN** an unstarted planned unit with a standing cause that another unit is joined onto
- **WHEN** the join is applied
- **THEN** the entry's note is `joined` and the cause is the one it had

#### Scenario: An event cause is not carried

- **GIVEN** a planned unit whose cause is `requeued`
- **WHEN** a replan omits it and a later one includes it again
- **THEN** its cause reads none

#### Scenario: A caller that passes no cause ends the cause

- **GIVEN** a unit whose cause is `rework`
- **WHEN** the unit's run starts and the store records `running` with no cause
- **THEN** the entry records no cause, as before

#### Scenario: A carry is not a parking

- **GIVEN** a unit parked for the code host with `parked_attempts` 2 and a step
- **WHEN** a replan demotes and promotes it
- **THEN** `parked_attempts` is 2 and its step is kept

### Requirement: A backoff counts from when the unit was parked

A unit parked for the code host, the network or the model service SHALL be measured from the time of the entry that set its cause, not from the latest entry. A carried entry SHALL NOT restart the wait, and a second parking SHALL, as before. The backoff step SHALL still be chosen by the count of consecutive parkings.

#### Scenario: A replan during a backoff

- **GIVEN** a unit parked for the code host 20 seconds ago, with a backoff of one minute
- **WHEN** a replan demotes and promotes it
- **THEN** 40 seconds of its backoff remain, not a minute

#### Scenario: A second parking restarts it

- **GIVEN** a unit parked for the code host twice in a row, the second time 20 seconds ago
- **WHEN** its backoff is read
- **THEN** it is measured from the second parking

### Requirement: A gate is closed in the write that changes the cause

A unit's record of a requeue that waits for a gate SHALL be cleared in the same write that records any cause other than `gated`. A unit with the cause `gated` and a saved requeue SHALL NOT be left with the cause and no requeue by a stop between two writes of the release, and a unit with a saved requeue SHALL NOT be left with another cause by a stop between them.

#### Scenario: The gate is delivered

- **GIVEN** a `gated` unit with a saved requeue whose waits have cleared and whose thread declines the delivery
- **WHEN** the release runs
- **THEN** the store never holds the cause `gated` without the requeue: one entry records `requeued` and the requeue is gone

#### Scenario: A gate and its cause are written in turn

- **WHEN** a requeue is recorded as `gated` and its saved requeue is set right after
- **THEN** the requeue is set

### Requirement: A replan keeps the runtime fields of a unit it rebuilds

A replan SHALL take a unit's shape from the plan and SHALL keep from the stored record every field that records what happened to the unit, including `parked_splits`, `parked_sha`, `parked_snapshot`, `parked_attempts`, `service_attempts`, `gated_requeue`, `waited_on`, `wait_ended`, `close_pending`, `step`, `guidance`, `ready_at` and `first_human_activity_at`. A unit new to the store SHALL have their defaults. A unit parked on a gate SHALL stay waiting and keep its requeue, and a unit parked on a held split SHALL NOT be resumed while the split is held.

#### Scenario: Each field survives a replan

- **GIVEN** a stored unit with a value in each of the thirteen fields
- **WHEN** a replan includes it, reshaped or not
- **THEN** each field has the value it had

#### Scenario: A gated unit after a replan

- **GIVEN** a unit requeued while its same-repo parent was unmet, `gated`, with a saved requeue
- **WHEN** a replan includes it
- **THEN** it still waits, and its saved requeue is delivered once when the parent is in review

#### Scenario: A split-held unit after a replan

- **GIVEN** a unit parked on the held split `acp`
- **WHEN** a replan includes it and the release step runs while `acp` is held
- **THEN** the unit is not resumed

#### Scenario: Nothing is lost from the history

- **WHEN** a replan runs over units in every state
- **THEN** no unit's history is shorter than before

### Requirement: A gated unit is released by its saved requeue

A planned unit with a saved requeue SHALL be delivered that requeue once nothing it waits for is left, whatever its cause says, and a tick SHALL NOT start it for as long as the requeue is saved. A `gated` unit with no saved requeue SHALL NOT be delivered anything. A unit parked for a held tier 2 split SHALL stay stopped until it is released.

#### Scenario: A requeue beside another cause

- **GIVEN** a planned unit with a saved requeue and the cause `requeued`, whose waits have cleared
- **WHEN** the release step runs
- **THEN** the requeue is delivered once

#### Scenario: Nothing to deliver

- **GIVEN** a planned unit with the cause `gated` and no saved requeue
- **WHEN** the release step runs
- **THEN** nothing is delivered

### Requirement: A conflict move that could not run leaves the restack owed

When a conflict move for a unit in review comes back deferred (a usage pause, a busy checkout, a branch that moved), the unit SHALL stay `in_review` with the cause `restack_deferred`, so the restack lane keeps owing the restack and a dependent-following pass keeps skipping the unit. A move that comes back planned or in conflict SHALL be as before.

#### Scenario: A deferred conflict move

- **GIVEN** a unit in review whose conflict move comes back deferred
- **WHEN** the unit is read
- **THEN** it is `in_review` with the cause `restack_deferred`, the lane owes it a restack and a pass that follows predecessors leaves it where it is

### Requirement: Every reader of a standing cause answers the same after a replan

The restack lane's decisions (a restack owed, a moved-base run owed), whether a predecessor's branch is changing and which units follow it, the parking of a unit sent back across repositories, the release of a unit parked on a split, the wait for room of a freshly unblocked unit, the count of units in progress, and the resume of a parked unit SHALL give the same answer for a unit with a standing cause after a demotion, a promotion and a replan as before them.

#### Scenario: The restack lane

- **GIVEN** units with each of `base_changed`, `restack_deferred`, `restack_conflict` and `restack_handed_back`
- **WHEN** a replan demotes and promotes them
- **THEN** a restack and a moved-base run are owed exactly when they were

#### Scenario: A split release and the count

- **GIVEN** a planned unit parked on a held split
- **WHEN** a replan demotes and promotes it
- **THEN** it is not released and holds no place among the units in progress

#### Scenario: Waiting for room

- **GIVEN** a unit with the cause `upstream_went_back` whose parent has come back
- **WHEN** a replan runs
- **THEN** it still waits for room under the limit

### Requirement: The status lists only units whose record has no cause

`abk status` SHALL list, as having no recorded cause, a held unit and a started planned unit whose latest cause is none, and SHALL NOT list a unit whose standing cause a replan carried forward.

#### Scenario: A record from before causes

- **GIVEN** a started planned unit whose history has no cause
- **WHEN** the status is read
- **THEN** it is listed as having no recorded cause

#### Scenario: A replanned unit

- **GIVEN** a started planned unit with a standing cause that a replan demoted and promoted
- **WHEN** the status is read
- **THEN** it is not listed
