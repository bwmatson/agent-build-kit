# unit-scheduling Specification

## Purpose
Defines when a pass decides what to build: continuously, as slots free and
dependencies clear, rather than once at the start.

## Requirements

### Requirement: A pass keeps its build slots full

While a pass is running, the pipeline SHALL re-evaluate what may be built each
time a unit finishes, and start what fits in the free slots, until nothing is in
flight and nothing is ready. The rules that decide readiness — the dependency
rules, the stack depth cap and the concurrency cap — SHALL be unchanged and
SHALL be applied on every evaluation. A unit already started in the pass SHALL
NOT be started again.

#### Scenario: A chain whose parent reaches review

- **WHEN** a unit finishes and its child's dependencies now allow it to start
- **THEN** the child starts in the same pass, without waiting for unrelated
  units in that pass to finish

#### Scenario: A slow sibling in another repo

- **WHEN** one unit's build lasts far longer than another's, and work is ready
- **THEN** the free slots are used while the slow unit continues

#### Scenario: A unit re-queued during the pass

- **WHEN** a unit is set back to planned while a pass is running, and a slot is
  free
- **THEN** that pass starts it rather than leaving it for the next one

#### Scenario: The caps still hold

- **WHEN** re-evaluation finds more ready units than free slots, or a chain
  already extends past the depth cap
- **THEN** no more than the cap are building at once, and the over-deep chain
  waits, exactly as before this change

### Requirement: A pass notices what the code host reports while it runs

Each time a pass re-evaluates what to build, it SHALL first refresh what the
code host reports, so that a dependency merged during the pass can release the
unit waiting on it, and review feedback arriving during a long pass is not left
until the pass ends. A refresh that fails SHALL be skipped rather than stopping
the pass, as it is today. Planning SHALL stay once per pass.

#### Scenario: A cross-repo dependency merges mid-pass

- **WHEN** a unit's cross-repo dependency merges while the pass is running
- **THEN** the dependent unit becomes startable in that pass

#### Scenario: The code host is unreachable

- **WHEN** a refresh fails during a pass
- **THEN** the pass logs it and carries on building

### Requirement: A pass that must stop, stops

When building a unit reports that the pass should stop — an exhausted usage
window, say — the pipeline SHALL stop starting further units in that pass rather
than discarding the report, and SHALL let already-running builds finish. A pass
narrowed to particular units SHALL stay narrowed for every evaluation.

#### Scenario: A usage window is spent mid-pass

- **WHEN** a build reports the pass should stop
- **THEN** nothing further is started, and the builds already in flight are left
  to finish and commit their work

#### Scenario: A pass narrowed to one unit

- **WHEN** a pass is asked to build one named unit and that unit finishes,
  unblocking another
- **THEN** the other is not started by that pass

### Requirement: The build cap is named for what it does

The limit on how deep a chain of open, same-repo dependencies may run before a new unit must wait to
start SHALL be configured as `stack_depth_build_cap`. Its behaviour SHALL be unchanged from the
single depth cap that preceded it.

#### Scenario: Starting a unit

- **WHEN** a planned unit's chain of open ancestors would exceed `stack_depth_build_cap`
- **THEN** it waits, exactly as the single depth cap caused it to wait before

### Requirement: A separate cap bounds how far a merge cascades a rebase

The workspace SHALL configure, separately from the build cap, the deepest a dependent's chain may run
and still be automatically rebased when the unit beneath it merges: `stack_depth_rebase_cap`. Where
an installation does not set it, it SHALL default to whatever the build cap resolves to, so that an
installation that only sets the build cap sees no change in behaviour.

#### Scenario: The default

- **WHEN** an installation sets a build cap and no rebase cap
- **THEN** the rebase cap has the same value, and nothing about restacking changes

#### Scenario: Set apart from the build cap

- **WHEN** an installation sets the rebase cap lower than the build cap
- **THEN** a stack may still grow to the build cap's depth, while a merge only cascades a rebase to
  the rebase cap's depth

### Requirement: A merge restacks a dependent only within the rebase cap

When a unit merges, each direct dependent's depth SHALL be measured against the graph with that merge
already recorded, and SHALL be restacked as today only when that depth is within the rebase cap. A
dependent beyond it SHALL NOT be restacked, and its branch SHALL be kept rather than removed as part
of that merge's cleanup.

#### Scenario: Within the cap

- **WHEN** a dependent's depth after the merge is within the rebase cap
- **THEN** it is restacked exactly as it would be with no rebase cap at all

#### Scenario: Beyond the cap

- **WHEN** a dependent's depth after the merge exceeds the rebase cap
- **THEN** it is not restacked, and the branch it depends on is not deleted as part of that merge

### Requirement: A dependent held for depth is a unit a person must act on

A dependent not restacked for exceeding the rebase cap SHALL be held, with the reason — naming the
depth and the cap — on its record, in the same sense any other held unit is one the pipeline will not
touch until a person or a later merge changes something.

#### Scenario: Reading why a unit is held

- **WHEN** a unit is held for exceeding the rebase cap
- **THEN** its record names the depth it reached and the cap it exceeded

### Requirement: A unit held for depth is reconsidered as later merges land

Because a dependent's depth only ever falls as its ancestors merge, the pipeline SHALL reconsider
every unit in the same repository currently held for exceeding the rebase cap whenever another merge
in that repository lands, and SHALL restack it automatically once its depth is again within the cap
— without a person retrying it by hand.

#### Scenario: Depth falls below the cap

- **WHEN** a unit held for exceeding the rebase cap has, after a later merge, a depth within the cap
- **THEN** it is restacked at that merge, and is no longer held

#### Scenario: Still beyond the cap

- **WHEN** a held unit's depth is still beyond the rebase cap after a later merge
- **THEN** it remains held, to be reconsidered at the next one

### Requirement: Free slots go to existing work first, within the limit

Among the units that may start, the pipeline SHALL start those with an open pull
request before those resuming a build that was paused or held before a pull request
was opened, and those before units that have never run. Within the first two,
units SHALL start in the order they were planned. Within the units that have never
run, units SHALL start in order of their effective priority (the most urgent priority
among the unit and every unit that waits on it) and, between units of equal effective
priority, of their effective age: the earliest planned position
among the unit and every unit that waits on it, directly or through a chain of
dependencies in any repository, not counting merged, closed or satisfied units or units the round excludes (those named
out by `--only`, held by a lease or in a backoff), with a tie going to the
unit's own planned position. The order SHALL NOT depend on the depth of a stack or on
how many units wait. This ordering SHALL apply only to units the other rules allow to
start: it SHALL NOT start a unit that is waiting on a dependency or past the depth
cap, and SHALL NOT start a unit that has never run while the limit on units in
progress is reached. A ready unit that has never run and is a prerequisite of a blocked unit that would
otherwise count is a handoff unit: it takes that unit's slot, one slot for each blocked unit and one unit for each
slot, several of them in order of effective priority, then effective age. A handoff unit SHALL NOT start ahead of a more urgent unit that has never run: among
units that have never run the order is effective priority, then handoff units before the others of equal priority, then effective age, then planned position. Open pull requests
and resumed builds still come first. A handoff unit SHALL start whenever no more urgent unit that has never run can, so the slot a blocked unit frees is not left empty. None of this SHALL exceed the limit or the cap on units running at once.

#### Scenario: A rework and a new unit compete for one slot

- **WHEN** one slot is free, and a unit with an open pull request that needs a
  rework and a unit that has never run are both ready
- **THEN** the unit with the open pull request starts, whichever was planned first

#### Scenario: A paused build and a new unit compete for one slot

- **WHEN** one slot is free, and a unit paused part-way through its build and a
  unit that has never run are both ready
- **THEN** the paused unit resumes first

#### Scenario: Only new units are ready

- **WHEN** every ready unit has never run and none has any unit waiting on it
- **THEN** they start in the order they were planned, as before

#### Scenario: A resuming unit at the limit

- **WHEN** the limit on units in progress is reached and a unit with no pull
  request is resuming a paused build
- **THEN** it resumes, because it is already in progress

#### Scenario: A prerequisite of an old unit goes ahead of newer work

- **GIVEN** a ready unit with an old unit waiting on it, and a newer ready unit that nothing waits on
- **WHEN** one place is free
- **THEN** the prerequisite starts first, although it was planned after the newer unit

#### Scenario: A prerequisite of a priority-1 unit goes ahead of an older priority-3 one

- **GIVEN** a ready priority-3 unit that a priority-1 unit waits on, and an older ready priority-3 unit that nothing waits on
- **WHEN** one place is free
- **THEN** the prerequisite starts first, whatever the ages

#### Scenario: A unit that gates several waiting units goes ahead of standalone ones

- **GIVEN** a ready unit planned late, with two older units waiting on it, and several ready units that nothing waits on and that were planned after the waiting ones but before it
- **WHEN** places free one at a time
- **THEN** the unit that gates the waiting ones starts first, and the standalone units follow in the order they were planned

#### Scenario: A prerequisite of only newer units does not take an older unit's place

- **GIVEN** a ready unit with only a newer unit waiting on it, and an older ready unit that nothing waits on
- **WHEN** one place is free
- **THEN** the older unit starts first

#### Scenario: A chain

- **GIVEN** a ready unit, a unit waiting on it, and an older unit waiting on that one
- **WHEN** the order is worked out
- **THEN** the ready unit takes the age of the oldest in the chain

#### Scenario: Depth and number of waiters do not matter

- **GIVEN** one ready unit with a long chain of newer units waiting on it, and another with one old unit waiting on it
- **WHEN** the order is worked out
- **THEN** the second starts first, because the unit waiting on it is older

#### Scenario: A unit waiting on two prerequisites

- **GIVEN** an old unit waiting on two ready prerequisites
- **WHEN** the order is worked out
- **THEN** both take its age

#### Scenario: A satisfied unit in the chain

- **GIVEN** an old unit that waits on a ready prerequisite through a unit that was satisfied
- **WHEN** the order is worked out
- **THEN** the prerequisite takes the old unit's age

#### Scenario: The limit is not exceeded

- **GIVEN** the limit on units in progress is reached and a ready prerequisite of an old unit
- **WHEN** units are chosen
- **THEN** it does not start, and starts when a place is free

#### Scenario: Work in progress is not displaced

- **GIVEN** a ready prerequisite of an old unit and a unit with an open pull request that needs a rework
- **WHEN** one place is free
- **THEN** the unit with the open pull request starts first

#### Scenario: Only the named units

- **GIVEN** a tick limited to named units and a ready prerequisite that is not named
- **WHEN** units are chosen
- **THEN** it is not started

#### Scenario: A unit left out by a lease or a backoff gives no age

- **GIVEN** an old unit that waits on a ready prerequisite and is itself left out of the round by a lease or a backoff, and a newer ready unit that nothing waits on
- **WHEN** one place is free
- **THEN** the newer unit starts first, because the old unit is not counted as waiting this round

#### Scenario: A waiter in another repo

- **GIVEN** a ready unit with an old unit in another repository waiting on it
- **WHEN** one place is free
- **THEN** the unit takes the old unit's age, as a waiter in its own repository would give it

#### Scenario: A prerequisite takes the slot of the unit it blocks

- **GIVEN** the limit is reached, one of the units in progress is blocked and has work, and its prerequisite is ready and has never run
- **WHEN** units are chosen
- **THEN** the blocked unit does not count, the prerequisite starts into its place ahead of every other unit that has never run and has the same effective priority, and the count stays at or below the limit

#### Scenario: Several handoffs are ordered by priority

- **GIVEN** two blocked units that have work, each with its own ready prerequisite, one waited on by a priority-1 unit and the other by an older priority-3 unit
- **WHEN** units are chosen and only one place can be given
- **THEN** the prerequisite of the priority-1 unit takes it

#### Scenario: Two blocked units and one prerequisite

- **GIVEN** the limit is reached by five units, two of them blocked on the same ready prerequisite
- **WHEN** units are chosen
- **THEN** the prerequisite takes one place, and the other place goes to the next unit by the usual order

#### Scenario: A prerequisite of a unit that never started

- **GIVEN** a ready prerequisite whose only waiter has never started
- **WHEN** units are chosen at the limit
- **THEN** it gets no place of its own, and follows the effective age order

#### Scenario: The handoff stays within the other rules

- **GIVEN** a prerequisite that is outside the units named by `--only`, held by a lease or in a backoff, or the cap on units running at once is reached
- **WHEN** units are chosen
- **THEN** it is not started

#### Scenario: A more urgent new unit starts before a handoff unit

- **GIVEN** a blocked unit with work that frees a place, its ready priority-2 prerequisite that has never run, and two ready priority-1 units that have never run and that nothing waits on
- **WHEN** units are chosen and there is room for all three
- **THEN** the two priority-1 units are offered before the priority-2 prerequisite, and the prerequisite starts after them

#### Scenario: Handoff units go first among equal priorities, then by age

- **GIVEN** two ready priority-3 handoff units, an older and a newer, and an older ready priority-3 unit that is not a handoff unit
- **WHEN** units are chosen
- **THEN** the older handoff unit starts first, the newer handoff unit second, and the unit that is not a handoff unit last, although it is the oldest

#### Scenario: Existing work still goes before a more urgent new unit

- **GIVEN** a paused priority-3 unit with work and a ready priority-1 unit that has never run, whichever is a handoff unit
- **WHEN** one place is free
- **THEN** the paused unit resumes first

#### Scenario: A less urgent handoff unit still gets the freed place

- **GIVEN** the limit is reached, one unit in progress is blocked and has work, and its only ready prerequisite is a priority-3 unit that has never run, with no more urgent ready unit
- **WHEN** units are chosen
- **THEN** the prerequisite starts into the blocked unit's place, and the count stays at or below the limit

#### Scenario: A more urgent unit that the limits skip leaves the place to the handoff unit

- **GIVEN** a freed place, a ready priority-1 unit of a project that is full, and a ready priority-3 handoff unit of a project with room
- **WHEN** units are chosen
- **THEN** the priority-1 unit is skipped and the handoff unit starts

### Requirement: A workspace bounds how many units are in progress

The workspace SHALL configure, once under `project_limits`, the greatest number of
units in progress at once in one project, defaulting to 5, and the limit SHALL apply to
each project separately: units in progress are counted for each project (a repo's
project, see the requirement that a unit has one project), no total is kept across
projects or repos, and a repo with one project counts as that one project. A unit SHALL be in
progress from the moment it first starts until it merges, is closed or is
satisfied, whatever state it is in meanwhile — running, in review, being
reworked, paused or held part-way, or failed — and whether or not it has a pull
request. A unit that has never started, including one waiting on a dependency,
SHALL NOT count. A started unit that is blocked (a planned unit waiting on another unit) SHALL NOT
count while it is blocked, and counts again from the moment it is not. A failed unit that waits on
another unit (the units it waits on are those that stop a unit starting: a dependency not yet merged or
reviewed, or a predecessor being reworked, failed or held) SHALL NOT count while it waits, SHALL count again from the moment
the wait ends, and SHALL stay failed throughout: it is never requeued by the pipeline.

#### Scenario: Started work without a pull request

- **WHEN** a unit is paused part-way through its build and has no pull request
- **THEN** it counts as in progress

#### Scenario: A failed unit

- **WHEN** a unit has failed and waits on no other unit (a failed unit that does wait is the next scenario)
- **THEN** it counts as in progress until it is requeued and finishes, or is
  closed

#### Scenario: A failed unit waiting on a prerequisite

- **WHEN** a unit has failed and waits on a prerequisite that has not merged, or on a predecessor that is being reworked, failed or held
- **THEN** it does not count, it is still failed, and it counts again, still failed and not requeued, when the wait ends

#### Scenario: Blocked new work

- **WHEN** a unit has never started and is waiting on a dependency
- **THEN** it does not count

#### Scenario: A blocked unit that has work

- **WHEN** a unit has a branch and a run log, is planned, and is waiting on a prerequisite that has not merged
- **THEN** it does not count, and counts again when the prerequisite has merged

#### Scenario: Two projects of one repo count apart

- **GIVEN** a repo with two projects and a limit of 5, five units in progress in one of them and two in the other
- **WHEN** the count is worked out
- **THEN** the first project is at its limit with five, the second has two, and neither count includes the other's units

#### Scenario: A repo with one project

- **GIVEN** a repo that declares one project, or none
- **WHEN** the count is worked out
- **THEN** its units are counted as one project, as the repo's units were counted before projects existed

#### Scenario: Another repo's units are not counted

- **GIVEN** a limit of 5, five units in progress in one repo and one in another
- **WHEN** the count is worked out
- **THEN** each repo's count is its own, and no figure of six is kept

### Requirement: At the limit, no new unit starts

While the number of units in progress in a project is at or above the limit, the
pipeline SHALL NOT start a unit of that project that has never started, and SHALL NOT
hold back a unit of any other project on account of it. Units waiting to start SHALL
stay as they are, to be started when that project's count falls.

#### Scenario: The limit is reached

- **WHEN** five units are in progress under the default limit and a unit that
  has never started is otherwise ready
- **THEN** it does not start, and remains planned

#### Scenario: A unit finishes

- **WHEN** a unit in progress merges and the count falls below the limit
- **THEN** a waiting unit may start under the other rules

#### Scenario: A full project does not stop another

- **GIVEN** one project at its limit and a unit that has never started, otherwise ready, in each of that project and another
- **WHEN** units are chosen
- **THEN** the other project's unit starts and the full project's stays planned

#### Scenario: A full project's ready units are skipped, not the pass

- **GIVEN** the units that are ready in start order are two of a full project and then one of another
- **WHEN** units are chosen with a free build slot
- **THEN** the full project's two are skipped and the third starts

### Requirement: Work already in progress continues at the limit

The limit SHALL NOT stop any unit that is already in progress. A rework, a
resume, a restack, a review round, a push and opening a pull request SHALL all
proceed at or over the limit, so work that is finished is never kept from its
pull request. A planned unit that was blocked and no longer is the exception: it SHALL start only while the number of
other units in progress is below the limit, and until then it stays planned.

#### Scenario: Finished work at the limit

- **WHEN** a unit completes its review loop while the count is at the limit
- **THEN** its branch is pushed and its pull request opened

#### Scenario: A rework at the limit

- **WHEN** a unit in review is sent back for rework while the count is at the
  limit
- **THEN** the rework runs

#### Scenario: A freshly unblocked unit at the limit

- **WHEN** a unit that was blocked becomes unblocked while the number of other units in progress is at the limit
- **THEN** it stays planned, and starts when a unit finishes

#### Scenario: A unit paused for usage at the limit

- **WHEN** a planned unit was paused by a usage pause, not blocked, while the count is at the limit
- **THEN** it resumes, as before

### Requirement: Holding at the limit is reported as such

When new work is held because a project's limit is reached, the tick's log and the
pipeline's status SHALL say so with one line for each full project, giving the project, the count, the limit, and
the units holding the places by state, rather than reporting that nothing is ready, and SHALL say how many blocked units of
that project are not counted and what each waits on. A failed unit that waits on another unit SHALL NOT be listed among the units holding the places, and the report SHALL say how many
of them are not counted. The line SHALL name the project when the workspace has more than one project, and SHALL read as it did before projects existed when it has one.

#### Scenario: A failed unit holding a place

- **WHEN** nothing new starts because the limit is reached and one of the units
  in progress has failed
- **THEN** the report lists that unit as failed among those holding the places

#### Scenario: Blocked units are listed

- **WHEN** the queue is full and two started units are blocked
- **THEN** the report says two blocked units are not counted and lists each with what it waits on

#### Scenario: A failed unit that waits is not listed as holding a place

- **WHEN** the queue is full and one failed unit waits on a prerequisite
- **THEN** the report does not count it or list it among the units holding the places, and says one failed unit waiting is not counted

#### Scenario: One line for each full project

- **GIVEN** a limit of 9 and two projects at it, `app/web` with seven failed and two running units and the other with nine in review
- **WHEN** the status is printed
- **THEN** it holds one queue line for each, `queue is full: app/web: 9 units in progress, limit 9 (7 failed, 2 running)` and the other's own, and no line for a project below its limit

#### Scenario: A workspace with one project

- **GIVEN** a workspace whose only repo has one project, at its limit
- **WHEN** the status is printed
- **THEN** the line reads `queue is full: 5 units in progress, limit 5 (...)`, with no project named

#### Scenario: Nothing started because a project is full

- **GIVEN** a pass that starts nothing because the only ready units belong to a full project
- **WHEN** its reason is printed
- **THEN** it holds that project's queue line and says no new unit of it starts until one finishes or is closed, and it does not name a project that holds no ready unit back

### Requirement: A task group may declare itself independent of the groups before it

A task group SHALL be able to declare, with a reason, that it does not depend on
any earlier group of its change. The unit built from such a group SHALL have no
dependency on the unit before it and SHALL be ready when its change is planned,
subject to its own `Needs` lines. The group following it SHALL depend on the
last unit before the independent group. A `[narrow]` or `[acceptance]` group
SHALL wait for every earlier unit of the change, independent or not, and SHALL
store only its direct dependencies, those that no other dependency of it reaches. An
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
- **THEN** the acceptance unit depends on the independent group's unit as well, and waits for it until it is in review

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

### Requirement: Events carry their kind

Events delivered to a unit SHALL carry a kind from a fixed set (the requeue reason, the
rework kind) beside any display text, and the handling of the event SHALL depend on the
kind. Feedback SHALL record its source, and the prompt chosen for it SHALL depend on the
source.

#### Scenario: A failing check sends a unit back

- **WHEN** the poller reports newly failing checks
- **THEN** the rework gets the CI log only, chosen by the event's kind

#### Scenario: Feedback that starts like a check failure

- **GIVEN** a reviewer's feedback whose text begins "unit-test failed:"
- **WHEN** it is saved and used
- **THEN** it is treated as review feedback, because its source says so

### Requirement: A unit's outcome and a usage pause are defined values

The outcome of a unit run SHALL be one of a fixed set shared by the graph, the CLI and
telemetry, and a usage pause SHALL carry its reason and resume time as fields, not as
the outcome's detail text. An unsupported toolchain SHALL be reported by its own
exception, and no other failure SHALL be classified as one.

#### Scenario: A usage pause

- **WHEN** a run pauses for the usage window
- **THEN** the pause's reason and resume time come from its fields

#### Scenario: A failure that is not the toolchain

- **WHEN** a run raises an unrelated `NotImplementedError`
- **THEN** it is not held as a toolchain problem

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

### Requirement: A running pass does everything a tick does before it starts builds

On every refresh, a running pass SHALL perform the same sequence a tick performs before it
starts builds: refresh from the code host, convert and plan new or changed changes, link
dependencies, verify and archive changes whose units have all merged, reclaim units no run
holds, and ask the usage guard, then start what fits in the free slots. The tick and the
pass SHALL use the same sequence. A step SHALL be safe to repeat, SHALL NOT alter the state,
branch or pull request of a unit being built, and a failure in one SHALL be logged without
ending the pass or skipping the others.

#### Scenario: A change written while a unit builds

- **GIVEN** a pass with a free slot and one unit building
- **WHEN** a new change is committed and the pass next refreshes
- **THEN** its units are in the store and the graph page
- **AND** a ready one starts in the free slot in the same round

#### Scenario: A change whose units have all merged

- **GIVEN** a change whose units have all merged while other units build
- **WHEN** the pass next refreshes
- **THEN** the change is verified and archived without waiting for the pass to end

#### Scenario: A killed run

- **GIVEN** a unit marked running whose run was killed, with no thread to resume
- **WHEN** the pass next refreshes
- **THEN** it is returned to planned and may start

#### Scenario: The usage window fills during a pass

- **WHEN** a round finds the guard refusing
- **THEN** it records the pause and starts nothing, and the builds in flight continue

#### Scenario: A comment resumes a unit while a pass runs

- **GIVEN** a unit in review and a pass with one other unit building
- **WHEN** a reviewer's comment resumes the unit's thread
- **THEN** the pass starts its rework in the same or the next round
- **AND** the unit never holds a slot without a run on it

#### Scenario: Nothing new

- **WHEN** a round finds nothing changed
- **THEN** no planning call is made and no unit's state changes

### Requirement: Verification does not run on a stack in use, and reclaim spares what the pass holds

A round SHALL run verification only when the live-stack lock is free, leaving the change for
the next round otherwise, and SHALL NOT reclaim a unit that a build in the pass holds or has
just been handed.

#### Scenario: A unit's live-stack run is in progress

- **GIVEN** a unit running its live-stack tests and a change ready to verify
- **WHEN** a round runs
- **THEN** verification is skipped and logged, and happens in a later round

#### Scenario: A unit just handed to a worker

- **GIVEN** a unit submitted to the pool whose worker has not yet taken its branch lock
- **WHEN** a round runs
- **THEN** the unit is not reclaimed

### Requirement: A unit whose step cannot reach the host is parked, not failed

When a step of a unit cannot complete because the code host is unavailable, the unit SHALL be
returned to planned with a host-unavailable cause, the failing step and the error text, SHALL be
readmitted by the running pass after a backoff that grows with each consecutive parking, and SHALL
resume at that step. A failure for any other reason (none of the host, the network and the model service being unavailable) SHALL fail the unit and SHALL record its error
text and step on the unit.

#### Scenario: The host is down when the pull request is opened

- **GIVEN** an approved, pushed unit whose pull request create is answered 500 on every attempt
- **WHEN** the step gives up
- **THEN** the unit is planned with the host-unavailable cause and the error text

#### Scenario: The host recovers

- **GIVEN** a parked unit whose backoff has elapsed and a host that answers
- **WHEN** the pass refreshes
- **THEN** the unit resumes at the step and the pull request opens

#### Scenario: Backoff grows

- **GIVEN** a unit parked for the third time
- **WHEN** the pass refreshes before its backoff has elapsed
- **THEN** the unit is skipped and the log says how long remains

#### Scenario: Another failure

- **WHEN** a step raises an error that is none of the host, the network and the model service being unavailable
- **THEN** the unit fails and its error text and step are on the unit

### Requirement: A unit whose work is already pushed resumes at the pull request step

A unit whose approved commit is its pushed head SHALL, when resumed after a failure of the pull
request step, go straight to that step, without running e2e-test again, without a review and without
reworking from saved feedback.

#### Scenario: An e2e-test unit

- **GIVEN** an e2e-test unit approved and pushed whose pull request step failed
- **WHEN** it is resumed
- **THEN** e2e-test does not run again

#### Scenario: A unit with saved feedback

- **GIVEN** a unit with saved feedback whose reworked commit is approved and pushed
- **WHEN** it is resumed after the pull request step failed
- **THEN** it does not go back to rework

### Requirement: A task group may carry a priority

A task group SHALL be able to carry a priority, an integer from 0 to 5 with 0 the most urgent (the emergency lane) and 5 the least, written as a `Priority:` line. A
line inside a group SHALL set that group's priority, and a line above the first group SHALL set the default for the change's
groups, which a group's own line overrides. A group with neither SHALL have priority 3. A value that is not an integer from 0 to
5 SHALL be reported with its line number and a message that names the range 0 to 5, and the task-tag listing SHALL show a group's priority when it is not 3, and, when a group
that depends on it (as the planner chains the groups, or by a `Needs:` line) is more urgent, the priority it will be promoted to
and the group that causes it. A change that has no such line SHALL be read as before.

#### Scenario: A group sets its own priority

- **GIVEN** a group with the line `Priority: 2`
- **WHEN** the change is read
- **THEN** the group's priority is 2

#### Scenario: A group may be priority 0

- **GIVEN** a group with the line `Priority: 0`
- **WHEN** the change is read
- **THEN** the group's priority is 0 and it is not read as having none

#### Scenario: A change default

- **GIVEN** a `Priority: 4` line above the first group and one group with `Priority: 2`
- **WHEN** the change is read
- **THEN** that group's priority is 2 and the others' is 4

#### Scenario: A change default of 0

- **GIVEN** a `Priority: 0` line above the first group and one group with `Priority: 2`
- **WHEN** the change is read
- **THEN** that group's priority is 2 and the others' is 0

#### Scenario: No line

- **WHEN** a group has no priority line and the change has no default
- **THEN** its priority is 3

#### Scenario: A value outside the scale

- **GIVEN** a `Priority:` line of `6`, `-1`, `high` or `2.5`
- **WHEN** the change's tags are checked
- **THEN** the line is reported with its number and a message naming 0 to 5, and the change is not accepted

#### Scenario: A change that existed before priority 0

- **GIVEN** a `tasks.md` whose priority lines are all from 1 to 5, or absent
- **WHEN** it is read
- **THEN** every group has the priority it had before

#### Scenario: The listing shows a promotion

- **GIVEN** group 5 at priority 3 that group 9 at priority 1 depends on through the chain
- **WHEN** `abk tags` lists the change
- **THEN** group 5 reads `(priority 3, promoted to 1 by group 9)` and a group nothing more urgent depends on reads as before

#### Scenario: The listing shows a promotion to 0

- **GIVEN** group 5 at priority 1 that group 9 at priority 0 depends on through the chain
- **WHEN** `abk tags` lists the change
- **THEN** group 5 reads `(priority 1, promoted to 0 by group 9)`, and group 9 reads `(priority 0)`

### Requirement: A unit has the priority of its most urgent group

A unit SHALL have the most urgent (smallest) priority among the groups it builds, including groups carried from other changes, and a priority of 0 SHALL count as a priority, never as none. A
unit that has not started SHALL be promoted to the priority of the most urgent unit that waits on it, as the requirement on promotion
says. A unit's effective priority SHALL be the most urgent priority among the unit and every unit that waits on it, directly or through a
chain of dependencies in any repository, not counting merged, closed or satisfied units or units the round excludes (those named
out by `--only`, held by a lease or in a backoff). A started unit SHALL keep the priority it started with, a promoted one included, when the
file changes, and a unit that has not started SHALL take the file's value when its change is next planned, and then be promoted again
if units still wait on it. A stored unit with no priority SHALL read as 3, and a stored priority of 0 SHALL read back as 0.

#### Scenario: A unit of several groups

- **GIVEN** a unit built from a group of priority 4 and a group of priority 2
- **WHEN** its priority is read
- **THEN** it is 2

#### Scenario: A unit with a priority-0 group

- **GIVEN** a unit built from a group of priority 0 and a group of priority 3
- **WHEN** its priority is read
- **THEN** it is 0

#### Scenario: A prerequisite takes the priority of what waits on it

- **GIVEN** a priority-3 unit that a priority-1 unit waits on, directly or through a chain
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 1

#### Scenario: A prerequisite of a priority-0 unit

- **GIVEN** a priority-3 unit that a priority-0 unit waits on, directly or through a chain
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 0

#### Scenario: Waiting units that are less urgent

- **GIVEN** a priority-3 unit that only priority-5 units wait on
- **WHEN** the effective priority is worked out
- **THEN** it is 3

#### Scenario: A waiter in another repository

- **GIVEN** a unit that a more urgent unit in another repository waits on
- **WHEN** the effective priority is worked out
- **THEN** it takes the waiter's priority, as a waiter in its own repository would give it

#### Scenario: A satisfied unit in the chain

- **GIVEN** a priority-1 unit that waits on a ready prerequisite through a unit that was satisfied
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 1

#### Scenario: A unit left out of the round gives no priority

- **GIVEN** a priority-1 unit that waits on a ready prerequisite and is left out of the round by a lease, a backoff or `--only`
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite does not take priority 1

#### Scenario: A started unit keeps its priority

- **GIVEN** a unit that has started, and its group's priority line is then edited
- **WHEN** the change is next planned
- **THEN** the unit keeps the priority it had, and a unit of the same change that has not started takes the new one

#### Scenario: A record from before priorities

- **WHEN** a stored unit has no priority
- **THEN** it reads as 3

#### Scenario: A stored priority 0 is kept

- **GIVEN** a unit of priority 0 written to the store
- **WHEN** the store is read again
- **THEN** its priority is 0, not the default 3

#### Scenario: A started unit keeps a promotion

- **GIVEN** a unit promoted from 3 to 1 by a waiter that then starts
- **WHEN** the waiter is merged and the change is replanned
- **THEN** the started unit still has priority 1 and still names the waiter it was promoted from

#### Scenario: A started unit keeps a promotion to 0

- **GIVEN** a unit promoted from 3 to 0 by a priority-0 waiter that then starts
- **WHEN** the waiter is merged and the change is replanned
- **THEN** the started unit still has priority 0, not 3, and still names the waiter it was promoted from

### Requirement: Priority orders ready units within their class

Within each of the classes of units that may start (those with an open pull request, those resuming a build, and those that have
never run), units SHALL start in order of effective priority, the most urgent first, and units of equal effective priority SHALL
start in the order the other ordering rules give. Priority SHALL NOT start a unit that is not ready, SHALL NOT move a unit ahead of
a unit of an earlier class, SHALL NOT stop or pause a running unit, and SHALL NOT raise the limit on units in progress or the cap
on units running at once. The status SHALL show the priority of units that are not 3, the order of the ready queue and why each
unit is where it is.

#### Scenario: A more urgent unit goes first

- **GIVEN** one place is free and two ready units that have never run, the later planned of priority 1 and the other of priority 3
- **WHEN** units are chosen
- **THEN** the priority-1 unit starts first

#### Scenario: A prerequisite of an urgent unit goes ahead of an older one

- **GIVEN** a ready priority-3 unit that a priority-1 unit waits on, and an older ready priority-3 unit that nothing waits on
- **WHEN** one place is free
- **THEN** the prerequisite starts first

#### Scenario: A prerequisite of only nice-to-have units does not take a normal unit's place

- **GIVEN** a ready priority-3 unit that only newer priority-5 units wait on, and an older ready priority-3 unit that nothing waits on
- **WHEN** one place is free
- **THEN** the older unit starts first

#### Scenario: Equal priority falls to the other rules

- **GIVEN** two ready units that have never run, with the same effective priority
- **WHEN** units are chosen
- **THEN** they start in the order the other ordering rules give, and in the order they were planned where those do not decide

#### Scenario: Work in progress is not displaced

- **GIVEN** a ready priority-1 unit that has never run, and a unit with an open pull request or a paused build, of priority 5
- **WHEN** one place is free
- **THEN** the unit with the pull request, then the paused build, starts first

#### Scenario: A running unit keeps running

- **GIVEN** the cap on units running at once is reached and a ready priority-1 unit
- **WHEN** units are chosen
- **THEN** no running unit is stopped and the priority-1 unit does not start

#### Scenario: The limit is not exceeded

- **GIVEN** the limit on units in progress is reached and a ready priority-1 unit that has never run
- **WHEN** units are chosen
- **THEN** it does not start, and starts when a place is free

#### Scenario: A unit that is not ready

- **GIVEN** a priority-1 unit waiting on a dependency, and a ready priority-5 unit
- **WHEN** one place is free
- **THEN** the priority-5 unit starts

#### Scenario: The status shows the order

- **GIVEN** a ready unit of priority 1 and ready units of priority 3
- **WHEN** the status is read
- **THEN** the priority-1 unit is marked, and the ready queue is listed in start order with the reason each is where it is

### Requirement: A person can plan a change again on demand

`abk replan` SHALL plan the changes it is given, or selects with `--all` or `--failed`, now, whatever the recorded hash says: it SHALL remove each
selected change's recorded plan, run the planner for those changes only, and link the `Needs:` lines as a tick does. A unit id SHALL be accepted
and mapped to its change. With no selector it SHALL list each change with the state of its plan, and the reason when its last plan was refused, and
plan nothing. `--forget` SHALL remove the
records, make no planner call, and leave the planning to the next tick. It SHALL refuse a name that is not a change, a change without a
`tasks.md` and a change whose task groups have tag errors, and plan nothing for them. Its exit status SHALL be 0 when every selected change
planned, 1 when any failed or was refused, and 2 for a usage error. A change whose every group belongs to a started unit SHALL be recorded without a
planner call and reported as such. A tick SHALL be unchanged: it SHALL plan a change only when its `tasks.md`
differs from the recorded plan or its last plan did not succeed and attempts remain.

#### Scenario: A change is planned although its plan is recorded

- **GIVEN** a change whose recorded plan matches its `tasks.md`
- **WHEN** `abk replan` is run with its name
- **THEN** the planner is asked for it, and its record is written with the new hash, no failed attempts and success

#### Scenario: A unit id names its change

- **WHEN** `abk replan` is given the id of a unit
- **THEN** the change that carries it is planned, and the command says which change that is

#### Scenario: A change that gave up

- **GIVEN** a change that stopped being planned after its failed attempts
- **WHEN** `abk replan --failed` is run
- **THEN** it is planned, and its failed attempts start over

#### Scenario: Every change

- **WHEN** `abk replan --all` is run
- **THEN** every active change is planned

#### Scenario: Forget only

- **WHEN** `abk replan --forget` is run with a name
- **THEN** its record is removed, the planner is not asked, and the next tick plans it

#### Scenario: No selector

- **WHEN** `abk replan` is run with no name and no selector
- **THEN** it lists each change with the state of its plan and the reason when its last plan was refused, plans nothing and exits with the usage status

#### Scenario: A change that cannot be planned

- **WHEN** the name is not a change, the change has no `tasks.md`, or its task groups have tag errors
- **THEN** the command says why, plans nothing for it, and exits with status 1

#### Scenario: A tick skips an unchanged change

- **GIVEN** a change whose recorded plan matches its `tasks.md` and succeeded
- **WHEN** a tick plans
- **THEN** the planner is not asked

#### Scenario: A change with nothing left to plan

- **GIVEN** a change whose every group belongs to a started unit
- **WHEN** `abk replan` is run with its name
- **THEN** the planner is not asked, the command says every group is built by a started unit, and the plan is recorded

### Requirement: A replan leaves started work alone and says what changed

A replan SHALL NOT change a unit that is running, in review, failed, held, merged or satisfied: its state, branch, pull request, feedback and history
SHALL stay. A planned unit SHALL take the new plan's shape, an unstarted planned unit the plan no longer contains SHALL become `unplanned`, and a join
the plan proposed SHALL be dropped when a unit started meanwhile. A planned unit that has started (it has a branch, a pushed commit, a pull request or an
approval) and that the plan no longer contains SHALL NOT become `unplanned`: it SHALL stay as it is, and the replan SHALL print that it was kept, that it has
work and is not in the plan, and the `abk retire` line that ends it. The command SHALL print only what differs from the store before the replan:
dependencies added and removed, estimate and tier changes, units that became `unplanned`, joins dropped, and each started unit it
left alone. It SHALL print nothing for a unit that did not change.

#### Scenario: Started and finished units are kept

- **GIVEN** units that are running, in review, failed, held, merged and satisfied
- **WHEN** their change is planned again
- **THEN** each keeps its state, branch, pull request and history, and each started one is reported as kept

#### Scenario: A stale dependency is removed

- **GIVEN** a planned unit that depends on a unit the new plan does not ask for, and a dependency that a `Needs:` line asks for
- **WHEN** its change is planned again
- **THEN** the first dependency is gone, the second remains, and the output says which was removed

#### Scenario: A unit the plan dropped

- **GIVEN** an unstarted planned unit that the new plan does not contain
- **WHEN** its change is planned again
- **THEN** it becomes `unplanned` and is reported

#### Scenario: A join dropped

- **GIVEN** a plan that proposes a join with a unit that started while the planner ran
- **WHEN** the plan is applied
- **THEN** the join is dropped and reported

#### Scenario: Nothing changed

- **GIVEN** a change whose new plan equals the stored one
- **WHEN** it is planned again
- **THEN** the command prints that nothing changed

#### Scenario: A planned unit with work that the plan omits is kept

- **GIVEN** a planned unit with a branch, parked on a held e2e-test split, that the new plan does not contain
- **WHEN** its change is planned again
- **THEN** it stays `planned` with its branch and history, it does not become `unplanned`, and the output says `kept: <unit> has work; not in the plan` and gives `abk retire <unit>` with a reason

### Requirement: The recorded plans are written safely

The file of recorded plans SHALL be read, changed and written under a lock and written atomically, so a command run beside a pass that is planning
does not lose an update.

#### Scenario: Two writers

- **GIVEN** two writers changing different changes' records at once
- **WHEN** both finish
- **THEN** both records are present

### Requirement: A failing plan names the way out

The message that a change is not planned until its `tasks.md` changes, and the status line for a failing plan, SHALL also say to run `abk replan`. A change whose attempts are used up SHALL be reported as given up with the command that plans every such change again, `abk replan --failed`, named.

#### Scenario: A change gives up

- **WHEN** a change reaches its allowed failed attempts
- **THEN** the message names `abk replan` as well as an edit of `tasks.md`

#### Scenario: The command for every given-up change

- **GIVEN** a change whose attempts are used up
- **WHEN** an operator runs `abk replan` with no selector
- **THEN** the change's line says it is given up and names `abk replan --failed`

### Requirement: A failed prerequisite with waiting units is named

When a failed unit has units waiting on it, the status SHALL list it with the number of units waiting and say it needs a requeue,
and the reason given when nothing could start SHALL name it.

#### Scenario: Units wait on a failed unit

- **GIVEN** a failed unit and two units waiting on it
- **WHEN** the status is read
- **THEN** it names the failed unit, says two units wait on it, and says to requeue it

#### Scenario: Nothing could start

- **GIVEN** the only unit that could unblock others is failed
- **WHEN** nothing is started
- **THEN** the reason names the failed unit and does not say only that nothing is ready

### Requirement: A blocked unit does not hold a place

A planned unit SHALL be blocked when a unit it depends on or must follow has not merged or been satisfied, when its predecessor is being
reworked, failed or held, or when its cause is `gated` or `upstream_went_back`. A backoff for the host being unavailable, a lease,
a tick limited to named units and a usage pause SHALL NOT make a unit blocked. A blocked unit SHALL be shown as blocked by the status and the graph, whatever its stored state.

#### Scenario: Waiting on a prerequisite

- **GIVEN** a planned unit with work whose prerequisite is in review
- **WHEN** the status is read
- **THEN** it is shown as blocked and is not counted

#### Scenario: A usage pause is not a block

- **GIVEN** a planned unit paused by a usage pause with no unmet prerequisite
- **WHEN** the count is worked out
- **THEN** it counts

#### Scenario: Kept from going back by its predecessor

- **GIVEN** a unit in review set back to planned because its predecessor is changing
- **WHEN** the count is worked out
- **THEN** it does not count until the predecessor is back in review

### Requirement: A unit in review follows its predecessor when the predecessor's branch is changing

On every pass, a unit in review SHALL be set back to `planned` with the cause `upstream_went_back`
and a note naming the predecessor when a same-repo predecessor is not in review, merged or satisfied
and its branch is changing. A predecessor that builds nothing (`unplanned` or `retired`) SHALL NOT be one whose branch is changing. A branch SHALL be changing when it has commits beyond the unit's last
pushed head, or the unit is being rebased, or the unit is itself waiting on a changing upstream. The
move SHALL be delivered to the unit's thread as an event, not made in the store alone. The
unit's approval, branch, pull request and thread SHALL be kept, a chain of dependents SHALL move in
one pass, and a branch whose claim is held SHALL be left for the next pass.

#### Scenario: A predecessor is reworked and commits

- **GIVEN** a unit in review stacked on a predecessor that has gone back for rework
- **WHEN** the predecessor's branch has a commit beyond its last pushed head
- **THEN** the dependent is `planned` with the cause `upstream_went_back`, its approval, branch,
  pull request and thread are kept, and the log names the predecessor

#### Scenario: The thread knows

- **GIVEN** a dependent set back by this pass
- **WHEN** its thread is read
- **THEN** it is still at the review wait and has received the event that parked the unit, so the release resumes it as it would any parked unit

#### Scenario: A predecessor is reworked and only replies

- **GIVEN** a unit in review stacked on a predecessor that is reworking
- **WHEN** the predecessor's branch head is still its last pushed head
- **THEN** the dependent stays in review

#### Scenario: A predecessor is rebasing

- **WHEN** the predecessor is rebasing onto a moved base
- **THEN** the dependent is set back to `planned` before the new head exists

#### Scenario: A predecessor failed before editing anything

- **GIVEN** a predecessor that failed with its branch head unchanged
- **WHEN** the pass runs
- **THEN** the dependent stays in review

#### Scenario: A predecessor failed after committing

- **GIVEN** a predecessor that failed with commits beyond its last pushed head
- **WHEN** the pass runs
- **THEN** the dependent is set back to `planned`

#### Scenario: A chain

- **GIVEN** a grandchild in review on a parent in review on a grandparent whose branch is changing
- **WHEN** the pass runs
- **THEN** the parent and the grandchild are both `planned` after one pass

#### Scenario: The predecessor merges

- **WHEN** the predecessor is merged
- **THEN** the pass does not move the dependent, and the merge retargets or restacks it as before

#### Scenario: The branch is busy

- **GIVEN** a dependent whose branch claim is held by a running step
- **WHEN** the pass would move it
- **THEN** it is left for the next pass without an error

#### Scenario: The predecessor returns to review

- **GIVEN** a dependent set back by this pass
- **WHEN** the predecessor is in review again on a new head
- **THEN** the dependent is released, restacks onto that head, and keeps its approval if the restack is clean

#### Scenario: The predecessor was dropped

- **GIVEN** a unit in review whose same-repo predecessor is `unplanned` or `retired` with a branch head beyond its last pushed head
- **WHEN** the pass runs
- **THEN** the dependent stays in review

### Requirement: What decides or counts by state asks the stored state

A check that decides what a unit may do, and a count of units by state, SHALL use the stored state, not the derived display name. The derived
names `reworking` and `rebasing` SHALL appear only where a status is shown.

#### Scenario: A chat on a unit that is reworking

- **GIVEN** a stored `running` unit that reads `reworking`
- **WHEN** a chat asks whether a step runs on it
- **THEN** it does

#### Scenario: Units counted by state

- **GIVEN** two stored `running` units, one of which reads `reworking`
- **WHEN** units are counted by state
- **THEN** the count for `running` is two

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

Each time a running pass refreshes, it SHALL append one `sample` row to the ledger with the counts of units running, in review, blocked and queued, the free workers, the limit and the cap, each a total over the projects that have a unit not yet finished and kept for reporting only (the limits themselves apply to each project and are never compared with a total), and SHALL set gauges for free slots and for idle slots with ready work, with no unit or change attribute. A reader that does not know the row kind SHALL skip it.

#### Scenario: One refresh

- **WHEN** a pass refreshes
- **THEN** exactly one sample row is written with those counts

#### Scenario: An unknown kind

- **WHEN** the report reads a ledger holding sample rows
- **THEN** its figures are unchanged

#### Scenario: Two live projects

- **GIVEN** two projects with unfinished units, a limit of 5 and a cap of 4
- **WHEN** a pass refreshes
- **THEN** the sample row's limit is 10, its cap is 8 and its free workers are the sum of each project's free workers

### Requirement: An edit to groups that have all started asks the planner for nothing

When a change's `tasks.md` differs from its recorded plan and every group of the change is claimed by a unit that has started (in flight, failed,
held, merged or satisfied), the pipeline SHALL record the new content as planned, with no failed attempts, and SHALL NOT call the planner. A unit
that is requeued SHALL read the edited group text from `tasks.md`. A tick after the edit SHALL make no call.

#### Scenario: Text edited on a failed unit's group

- **GIVEN** a change whose only group is built by a failed unit
- **WHEN** the text of that group is edited and the change is planned
- **THEN** the planner is not asked, the new content is recorded as planned with no failed attempts, and the unit's next run reads the edited text

#### Scenario: Text edited on a merged unit's group

- **GIVEN** a change whose groups are all built by merged units
- **WHEN** the text of a group is edited and the change is planned
- **THEN** the planner is not asked and the new content is recorded as planned

#### Scenario: A tick after the edit

- **GIVEN** an edit recorded without a planner call
- **WHEN** a tick plans
- **THEN** the planner is not asked

#### Scenario: A group still to plan

- **GIVEN** a change with one group no started unit claims
- **WHEN** it is planned after an edit
- **THEN** the planner is asked, with the started groups passed as built

### Requirement: A tag change under a started unit is reported and not applied

When a started unit's stored repo, project, tier or flag differs from the tags of the groups it carries, the pipeline SHALL report the unit, the difference
and the way out (`abk requeue --restart` on the unit, or restoring the tag), SHALL NOT change the unit, and SHALL NOT record the plan as done, so the
report repeats until it is resolved. Renumbering or deleting a group a started unit carries SHALL be refused as before.

#### Scenario: A tier changed on a failed unit's group

- **GIVEN** a failed unit and its group, which is then re-tagged with another tier
- **WHEN** the change is planned
- **THEN** the unit and the difference are reported with the way out, the unit is unchanged and the plan is not recorded as done

#### Scenario: The report ends

- **GIVEN** a reported tag change
- **WHEN** the tag is restored, or the unit is requeued with `--restart` and takes the new tags
- **THEN** the next planning records the plan and reports nothing

#### Scenario: A started group renumbered or deleted

- **GIVEN** a group a started unit carries
- **WHEN** it is renumbered or deleted and the change is planned
- **THEN** the plan is refused with the existing message and no planner call is made

#### Scenario: A project changed on a failed unit's group

- **GIVEN** a failed unit built for the root project and its group, which is then tagged for another project
- **WHEN** the change is planned
- **THEN** the unit and the difference are reported with the way out, the unit is unchanged and the plan is not recorded as done

### Requirement: The planner is told which groups are taken

The planner's instructions SHALL say that groups marked as built are taken, are never to be claimed, and get no unit; and the text of the change sent to
it SHALL mark the heading of each group a started unit builds with `(built by <unit id>)` and no other heading. A plan that claims a built group SHALL
still be refused and nothing stored for it.

#### Scenario: The rule and the marker

- **GIVEN** a started unit that builds one group of a change
- **WHEN** the planner's prompt is built
- **THEN** it states the rule, and only that group's heading is marked `(built by <unit id>)`

#### Scenario: A planner that claims a built group

- **GIVEN** a planner reply with a unit claiming a group a started unit builds
- **WHEN** the plan is checked
- **THEN** it is refused and no unit is stored for it

### Requirement: A refused plan keeps its reason

A failed plan SHALL store the reason in the change's plan record, whether the planner returned a plan that was refused or the attempt raised or could not be made, and a refused plan SHALL store as well the labels the planner gave its units (the ids of the units when the reply used them as labels), not the planner's full reply. The reason SHALL be the first line of the error, at most 300 characters, with secrets removed by the same redaction as printed output, and a bare `abk replan` SHALL show the reason beside the plan state. A later successful plan SHALL clear it.

#### Scenario: The reason is shown

- **GIVEN** a plan refused because it claimed a built group
- **WHEN** `abk replan` is run with no selector
- **THEN** the change's line shows the failing state and the reason

#### Scenario: The reason is cleared

- **GIVEN** a record with a refusal reason
- **WHEN** the change is next planned successfully
- **THEN** the record has no reason

#### Scenario: A call that failed keeps its reason

- **GIVEN** a planner call that ends in an ordinary failure with a message of several lines and more than 300 characters
- **WHEN** the attempt is recorded
- **THEN** the attempt is counted and the record keeps the first line of the message cut to 300 characters

#### Scenario: A secret does not reach the record

- **GIVEN** a failure whose message contains a value the redaction set knows
- **WHEN** the attempt is recorded
- **THEN** the stored reason does not contain it

### Requirement: The status shows who holds the e2e-test lock

`abk status` SHALL show, when the e2e-test lock is held, the unit that holds it and how long it has held it. A record of a holder whose process is gone,
while the lock is free, SHALL be shown as stale and not as a holder; a lock that is held while its recorded process is gone SHALL be shown as held
and say so. When the lock is free and has no record, the status SHALL show no e2e-test line. Reading the status SHALL NOT leave the lock held or change
its file.

#### Scenario: A held lock

- **GIVEN** a unit holding the e2e-test lock since forty minutes ago
- **WHEN** `abk status` is run
- **THEN** it shows that unit as the holder and an age of forty minutes

#### Scenario: A stale record

- **GIVEN** a free lock whose record names a process that is gone
- **WHEN** `abk status` is run
- **THEN** the record is shown as stale, not as a holder, and the file is unchanged

#### Scenario: A free lock

- **GIVEN** a free lock with no record
- **WHEN** `abk status` is run
- **THEN** no e2e-test line is shown

#### Scenario: A held lock whose recorded process is gone

- **GIVEN** a held lock whose record names a process that is gone
- **WHEN** `abk status` is run
- **THEN** it shows the lock as held and says the recorded process is gone

#### Scenario: Reading the status leaves the lock alone

- **GIVEN** a free lock
- **WHEN** `abk status` is run and a unit then asks for the lock
- **THEN** the unit gets it at once

### Requirement: A planner edge never closes a cycle with stored work

After a plan is parsed and before it is stored, the pipeline SHALL check the plan's dependencies against the whole graph of units that are not
finished: every stored unit's dependencies, the plan's units, and the dependencies the `Needs:` lines of every change declare toward them. A
dependency the planner proposed that would close a cycle SHALL be dropped from the plan, the drop SHALL be logged naming the cycle, and the rest of
the plan SHALL stand. A dependency a `Needs:` line declares SHALL NOT be dropped for a planner dependency. A cycle made only of `Needs:` and stored
dependencies SHALL leave the plan standing and be reported as an error, and a replan of that change SHALL exit non-zero naming it.

#### Scenario: A planner edge back into a change that needs it

- **WHEN** a stored unit of a second change depends on the first change's group 1 through a `Needs:` line, and the plan for the first change has its unit 1 depend on that second unit
- **THEN** the dependency of unit 1 on the second unit is dropped, the log names the cycle, and unit 1 is ready

#### Scenario: A planner edge closing a cycle through another planner edge

- **WHEN** a stored unit depends, by the planner's own earlier edge, on a unit the new plan gives a dependency on it
- **THEN** the new dependency is dropped and the stored one stays

#### Scenario: A planner edge that closes no cycle

- **WHEN** a plan has a dependency on a stored unit that is not part of any cycle
- **THEN** the dependency is kept

#### Scenario: A longer cycle across three changes

- **WHEN** a plan's dependency would close a cycle through units of two other changes
- **THEN** it is dropped and the log names all three changes' units in order

#### Scenario: A diamond or a chain is not a cycle

- **WHEN** units depend on each other as a chain or as a diamond across changes
- **THEN** no dependency is dropped and nothing is reported

#### Scenario: A cycle with no planner edge in it

- **WHEN** the `Needs:` lines and the stored dependencies alone form a cycle
- **THEN** the plan stands unchanged, the cycle is reported as an error, and a replan exits non-zero

### Requirement: A `Needs:` dependency that would close a cycle is refused

When the pipeline applies a `Needs:` line as a dependency, it SHALL NOT add one that would close a cycle with the unit graph as linked so far. The
unit SHALL keep the dependencies it had, its other `Needs:` dependencies SHALL still be applied, and the log SHALL name the refused dependency and
the cycle. A dependency already stored SHALL be left alone. A replan SHALL exit non-zero when a dependency was refused, and a tick SHALL log it and
carry on.

#### Scenario: The edge closes a cycle

- **WHEN** a `Needs:` line would make a unit depend on a unit that already waits, directly or through others, on it
- **THEN** the dependency is not added, the unit keeps its dependencies, and the log names the cycle

#### Scenario: Another Needs of the same unit

- **WHEN** one of a unit's two `Needs:` lines is refused for a cycle
- **THEN** the other is still applied

#### Scenario: A replan that refused one

- **WHEN** `abk replan` links a `Needs:` and one is refused
- **THEN** it prints the cycle and exits non-zero, and a tick that links the same line logs it once and does not fail

#### Scenario: A cycle already stored

- **WHEN** the store already holds a cycle an older version wrote
- **THEN** linking removes nothing and refuses nothing, and the status reports the deadlock

### Requirement: A cycle in `Needs:` lines is an error before any planning

`abk tags` and `abk check` SHALL report a cycle formed by the `Needs:` lines of two or more changes and the order of each change's consecutive groups
(a group marked `Independent:` has no edge to the one before), naming each group in it, counting it as a problem in each change that has a `Needs:`
line on it, and exiting non-zero.

#### Scenario: Two changes that need each other

- **WHEN** group 2 of one change needs group 1 of another, which needs group 2 of the first
- **THEN** `abk tags` names the cycle under each change and exits non-zero, and `abk check` reports it too

#### Scenario: A chain or a diamond across changes

- **WHEN** the `Needs:` lines form a chain or a diamond
- **THEN** nothing is reported

#### Scenario: A Needs on the change's own group or an independent group

- **WHEN** a `Needs:` names a group of its own change, or the group is independent
- **THEN** no cycle is reported and the other messages are unchanged

### Requirement: A deadlock in the stored graph is reported

When planned units wait on each other in a cycle, `abk status` SHALL list each cycle once as `deadlocked:` followed by its units in order, the reason
a pass that starts nothing SHALL name the deadlock ahead of any other reason, and the ready-queue report SHALL give the units in it, and the units
waiting on them, that reason. A deadlock SHALL NOT be reported as a full queue or as nothing ready. It SHALL be derived from the stored dependencies
each time, so removing an edge ends it, and nothing SHALL break it automatically.

#### Scenario: Two units wait on each other

- **WHEN** two planned units depend on each other
- **THEN** the status shows one `deadlocked:` line naming both and the cycle, not one per unit

#### Scenario: Two separate cycles

- **WHEN** the graph holds two disjoint cycles
- **THEN** the status shows two lines

#### Scenario: A pass that starts nothing

- **WHEN** nothing starts because every ready candidate is in or behind a cycle
- **THEN** the log says `nothing can start: deadlocked:` and the cycle, not "queue is full" or "nothing ready to build"

#### Scenario: A unit behind the cycle

- **WHEN** a unit waits on a unit that is in a cycle
- **THEN** the ready-queue report says it waits on the deadlocked unit, and units outside the cycle start as usual

#### Scenario: The edge is removed

- **WHEN** a person replans or edits a `Needs:` line so the cycle is gone
- **THEN** the next status reports no deadlock

#### Scenario: No false report

- **WHEN** planned units form a chain or a diamond
- **THEN** no deadlock is reported

### Requirement: A replan clears a stale planner edge and leaves started units alone

A replan SHALL replace the dependencies of a unit that has not started with the plan's, so a planner dependency dropped for a cycle is gone from the
stored unit. The dependencies of a unit that has started SHALL never be changed by a plan, a dropped edge or a refused `Needs:`. The linking that follows
a plan MAY replace a stored dependency on a replaced unit by its successors, in a unit of any state, as the requirement on repointing says; it SHALL
change no other dependency of a started unit.

#### Scenario: A stale edge on an unstarted unit

- **WHEN** an unstarted unit stores a planner dependency that closes a cycle and its change is replanned
- **THEN** the stored unit no longer has it and its state, branch and history are unchanged

#### Scenario: A started unit

- **WHEN** a running, in-review, failed or held unit of the change has dependencies and the change is replanned
- **THEN** its dependencies are the same afterwards, and a cycle through it is reported rather than edited

### Requirement: The planner is told not to close a cycle

The planner's prompt SHALL say that a unit shown as not yet started must not be made to depend, directly or through others, on a unit of the change
being planned. This is advice; the check of a planner edge against stored work is the guarantee, and SHALL NOT depend on the planner following it.

#### Scenario: The prompt

- **WHEN** the prompt is built with an unstarted unit of another change in flight
- **THEN** it carries that rule beside the in-flight units

#### Scenario: A planner that ignores it

- **WHEN** the planner returns a dependency that closes a cycle anyway
- **THEN** the dependency is dropped as above and the plan stands

### Requirement: A failed unit that waits is shown as waiting

The status and the graph SHALL show a failed unit that waits on another unit as failed and waiting, naming the units it waits on, and SHALL
NOT change its state, its pull request or its labels there. Its wait ending SHALL NOT start it, requeue it or give it a place ahead of any other unit.

#### Scenario: The status

- **WHEN** a failed unit waits on a prerequisite and the status is read
- **THEN** the status shows it as failed, waiting on that prerequisite, in addition to its failed line

#### Scenario: The graph

- **WHEN** the graph is drawn with a failed unit that waits on a prerequisite
- **THEN** the unit is drawn as failed with the label `failed, waiting on` and the prerequisite, and a failed unit that waits on nothing is drawn as failed

#### Scenario: The wait ends at the limit

- **WHEN** a failed unit's wait ends while the count of the other units is at the limit
- **THEN** the unit counts again and starts nothing, no unit already in progress is stopped, and no new unit starts until the count falls below the limit

### Requirement: A Needs line starts the dependent on the parent's branch

A `Needs: <change> group <n>` line SHALL add a dependency of the unit on the unit that holds that group, and
nothing more, unless the unit already reaches that unit through its dependencies, in which case no dependency
is added and the line is applied by the one that reaches it. A same-repo dependency SHALL release its dependent once it is through its build and review loop
(in review, merged or satisfied), and the dependent SHALL start on that dependency's branch, as for any
same-repo dependency. A dependency in another repository SHALL release its dependent only once it has merged,
or been satisfied with its work landed, because a stack cannot span repositories. A dependency that is planned,
running, reworked, failed or held SHALL keep its dependent from starting. A `Needs:` line SHALL be applied on
the next tick without re-planning the change.

#### Scenario: A same-repo parent in review

- **WHEN** a unit needs a same-repo unit and that unit is in review
- **THEN** the dependent may start, on the parent's branch

#### Scenario: A parent still building

- **WHEN** a unit needs a same-repo unit that is planned, running, failed or held
- **THEN** the dependent does not start

#### Scenario: A parent that goes back for rework

- **GIVEN** a unit that needs a same-repo unit, and that parent is sent back for rework
- **WHEN** the pass looks for units to start
- **THEN** the dependent is paused as any dependent of that unit is, and returns when the parent is back in review

#### Scenario: A cross-repo parent

- **WHEN** a unit needs a unit in another repository that is in review
- **THEN** the dependent does not start until that unit has merged

#### Scenario: Only a Needs line changed

- **WHEN** an edit changes a `Needs:` line and nothing else in `tasks.md`
- **THEN** no planner call is made and the dependency applies on the next tick

#### Scenario: The word merged is not a qualifier

- **WHEN** a `Needs:` line carries the word `merged` straight after the group number
- **THEN** the line means the same as without it, and `abk tags` and `abk check` warn that the word is deprecated, without failing or stopping planning

#### Scenario: A Needs on the change's own group

- **WHEN** a `Needs:` line carrying the word `merged` names a group of its own change
- **THEN** `abk tags` reports an error: the groups of one change are ordered already

#### Scenario: A stored merge gate from before

- **GIVEN** a stored unit that carries a `merge_before` from an earlier version
- **WHEN** the next tick reads the store
- **THEN** the store loads, the key is dropped, and the unit waits only for what a dependency requires

#### Scenario: A target the chain already implies

- **GIVEN** a unit whose dependency chain already reaches the unit a `Needs:` line names
- **WHEN** the next tick applies the line
- **THEN** no dependency is added, the unit's dependencies are unchanged, and the line is not applied again on any later tick

### Requirement: The graph page marks a Needs dependency

The unit graph page SHALL draw a dependency written as a `Needs:` line with a thick edge labelled `needs`, and a dependency the
planner inferred without a label or the thick style, and a `Needs:` dependency the chain already implies SHALL
draw no edge at all, and the legend SHALL say so, so a reader can tell a stated
dependency from an inferred one.

#### Scenario: A Needs dependency

- **WHEN** a unit has a dependency written as a `Needs:` line
- **THEN** the page draws that edge thick and labelled `needs`

#### Scenario: An inferred dependency

- **WHEN** a unit depends on another through the planner's own dependency
- **THEN** the page draws that edge without the label or the thick style

#### Scenario: The line is removed

- **WHEN** a `Needs:` line is removed and the dependency is not otherwise asked for
- **THEN** the edge is gone at the next tick

#### Scenario: A Needs line the chain implies

- **GIVEN** a unit that needs a unit its own parent already depends on
- **WHEN** the page is drawn
- **THEN** no edge is drawn for the line, and the edge to the parent is plain

### Requirement: A Needs line added to a started unit waits for the parent to be reviewed

A `Needs:` line added to a task group after its unit has started SHALL apply on the next tick without
re-planning the change, and SHALL be an ordinary dependency. A unit that is `failed` or `held` while a
dependency is unmet SHALL NOT be resumed by `abk requeue`: it SHALL become `planned` with the cause `gated`,
keep its thread, branch and saved feedback, remember the mode it was requeued with, and be resumed in that mode by the pass
once the dependency is in review (same repo) or has merged (other repo), restacked onto the dependency's branch. A unit that is running
SHALL NOT be interrupted by the line itself; it SHALL stop at its next check through the same path as a unit whose
parent went back, and a unit in review SHALL NOT be moved until it is next sent back for rework.

#### Scenario: A failed unit is requeued before its parent is reviewed

- **GIVEN** a failed unit with a thread, and a `Needs:` line added to its group for a group that is not yet in review
- **WHEN** the operator runs `abk requeue` on it
- **THEN** the unit is `planned` with the cause `gated`, its thread and branch are kept, no agent runs, and the command names the group it waits for

#### Scenario: The parent is in review

- **GIVEN** that gated unit
- **WHEN** the parent is in review and the pass runs
- **THEN** the unit resumes in the mode it was requeued with, on the parent's branch

#### Scenario: A running unit is not interrupted by the line

- **GIVEN** a unit with an agent step in progress
- **WHEN** a `Needs:` line is added to its group
- **THEN** the step finishes, and the tick logs once that the unit now depends on the parent

#### Scenario: A unit sent back for rework while its parent is not reviewed

- **GIVEN** an in-review unit with a `Needs:` dependency that is not in review and a review comment that sends it back
- **WHEN** the pass looks for units to readmit
- **THEN** the unit is `planned` and waits, not started, until the dependency is in review

#### Scenario: The status shows the wait

- **GIVEN** a gated unit
- **WHEN** an operator runs `abk status`
- **THEN** it is listed as waiting on the dependency group, not as failed or held

#### Scenario: A unit parked for a flaky test

- **GIVEN** a unit whose checks met a flaky test and the change written to fix it
- **WHEN** that change's unit is in review
- **THEN** the parked unit resumes, restacked onto the fix's branch

### Requirement: A unit whose agent run cannot reach the network is parked, not failed

When an agent run of a unit ends because the whole network is unavailable, the unit SHALL be returned to planned with a network-unavailable cause,
the failing step and the error text, SHALL keep its thread, branch and saved feedback, SHALL NOT be counted as failed and SHALL NOT be charged a
review, rework or check round, and SHALL be readmitted by the running pass after the same backoff as a unit parked for the host, resuming at that
step in the mode it was in. A failure that carries a strong sign of an outage (a name that cannot be resolved, a network that is unreachable) SHALL
park the unit on that evidence. A failure that carries a weak sign (one a reachable network can also produce) SHALL park the unit as
network-unavailable only when a bounded connectivity probe, which makes no model call, finds both the host the run called and every host of a
control group unreachable; a failure for any other reason SHALL fail the unit.

#### Scenario: The network is down during an implement step

- **GIVEN** a unit whose implement run ends on a name that could not be resolved
- **WHEN** the step gives up
- **THEN** the unit is planned with the network-unavailable cause, the step and the error text, and is not failed

#### Scenario: The whole network is down

- **GIVEN** a run that ends on a connect timeout while the probe reaches neither the API host nor any control host
- **WHEN** the step gives up
- **THEN** the unit is parked with the network-unavailable cause and not the service-unavailable one

#### Scenario: The unit resumes by itself

- **GIVEN** a parked unit whose backoff has elapsed
- **WHEN** the pass refreshes
- **THEN** the unit resumes at the step it stopped on, and a session it was continuing is continued

#### Scenario: No round is charged

- **GIVEN** a unit parked for the network at its rework step
- **WHEN** it resumes
- **THEN** its review, rework and check round counts are what they were before the step

#### Scenario: A weak sign with the API host reachable

- **GIVEN** a run that ends on a refused connection while the probe reaches the API host
- **WHEN** the step gives up
- **THEN** the unit fails with the error text and step

#### Scenario: A probe that errors does not park

- **GIVEN** a run that ends on a weak sign of an outage and a probe that raises an error
- **WHEN** the step gives up
- **THEN** the unit fails with the error text and step and is not parked

### Requirement: A unit whose agent run meets a model service that is down is parked, not failed

When an agent run of a unit ends because the model service is unavailable while the network works, the unit SHALL be returned to planned with a
service-unavailable cause, the failing step and the error text, SHALL keep its thread, branch and saved feedback, SHALL NOT be counted as failed
and SHALL NOT be charged a review, rework or check round, and SHALL be readmitted by the running pass after the same backoff as a unit parked for
the host, resuming at that step in the mode it was in. The service SHALL be taken as unavailable in two cases: a weak sign of an outage while the
connectivity probe finds the host the run called unreachable and at least one control host reachable, which parks without a cap; and a failure that
carries an HTTP status of 500 to 599, an overloaded 529 among them, after the runtime's own retries, which parks at most a configured number of times in
a row (`limits.service_unavailable_attempts`, default 5, a positive whole number checked at load) and then fails the unit with its error text and
step. A probe that cannot run SHALL count as the host being reachable. A 4xx status, a 401 or 403, a 429 usage or rate limit, a model refusal and a
permission or tool failure SHALL fail the unit as before.

#### Scenario: A provider outage with the network up

- **GIVEN** a run that ends on "Can't reach the API server" while the probe reaches no API host and reaches a control host
- **WHEN** the step gives up
- **THEN** the unit is parked with the service-unavailable cause and not the network-unavailable one, and is not failed

#### Scenario: The forge host is up and the API host down

- **GIVEN** a weak sign of an outage, an API host that does not connect and a forge host that does
- **WHEN** the step gives up
- **THEN** the unit is parked with the service-unavailable cause

#### Scenario: An overloaded service parks, bounded

- **GIVEN** a unit whose run ends on the status 529 after the runtime's own retries
- **WHEN** the step gives up
- **THEN** the unit is planned with the service-unavailable cause, the step and the error text

#### Scenario: The cap is reached

- **GIVEN** a unit that has been parked for a 5xx or 529 as many times in a row as `limits.service_unavailable_attempts` allows
- **WHEN** its next run ends on a 5xx or 529
- **THEN** the unit fails with the error text and step

#### Scenario: The attempts setting is checked

- **GIVEN** `limits.service_unavailable_attempts` set to 0, to a negative number or to a number that is not whole
- **WHEN** the configuration is loaded
- **THEN** it is refused with a message naming the key, and the default is 5

#### Scenario: A rejected key still fails

- **GIVEN** a unit whose run ends on a 401
- **WHEN** the step gives up
- **THEN** the unit fails with the error text and step

#### Scenario: A model refusal still fails

- **GIVEN** a unit whose run ends on a model refusal
- **WHEN** the step gives up
- **THEN** the unit fails with the error text and step

#### Scenario: A probe that errors does not park

- **GIVEN** a run that ends on a weak sign of an outage and a probe that raises an error
- **WHEN** the step gives up
- **THEN** the unit fails and is not parked as service-unavailable

#### Scenario: A provider outage does not stop other work

- **GIVEN** a unit parked with the service-unavailable cause
- **WHEN** a tick runs
- **THEN** no network pause is written for it and the tick starts ready units as usual

### Requirement: The two outage causes are shown differently

The status, the unit graph and the unit page SHALL show a unit parked with the network-unavailable cause as waiting for the network and a unit parked
with the service-unavailable cause as waiting for the model service, each with the step and the time remaining, and neither as failed.

#### Scenario: Waiting for the network

- **GIVEN** a unit parked with the network-unavailable cause and its backoff running
- **WHEN** an operator runs `abk status`
- **THEN** it is listed as waiting for the network, with its step and the time remaining, not as failed

#### Scenario: Waiting for the model service

- **GIVEN** a unit parked with the service-unavailable cause and its backoff running
- **WHEN** an operator runs `abk status`
- **THEN** it is listed as waiting for the model service, with its step and the time remaining, not as failed and not as waiting for the network

### Requirement: An outage of the whole network stops new agent runs until it is back

When a unit is parked with the network-unavailable cause, the pipeline SHALL pause the starting of agent runs with a network pause that is visible in
the status and the run log. While it stands, a tick SHALL start no agent run, and SHALL end it on the first tick whose connectivity probe finds a
control host reachable, whatever time the pause was given. A unit parked with the service-unavailable cause SHALL NOT write or extend this pause.
Usage and rate-limit pauses SHALL behave as before.

#### Scenario: The probe still fails

- **GIVEN** a network pause and a probe that finds no control host reachable
- **WHEN** a tick runs
- **THEN** no agent run starts and the log says it is waiting for the network

#### Scenario: The network is back

- **GIVEN** a network pause and a probe that reaches a control host
- **WHEN** a tick runs
- **THEN** the pause is cleared and ready units start as usual

#### Scenario: A failure of the unit's own

- **GIVEN** a unit that runs and fails for a reason with no sign of an outage
- **WHEN** the step gives up
- **THEN** the unit fails, whether or not a network pause stood before it ran

### Requirement: A planning attempt is not spent on an outage

When the planner's model call of a change ends because the whole network is unavailable, or because the model service is unavailable, the pipeline SHALL NOT count it as a failed attempt. The change's plan record SHALL keep the attempt count it had, SHALL say it is waiting for the network or for the model service with the time it began waiting and the time of the next try, and SHALL keep the reason. The next try SHALL be after the same backoff steps as a parked unit (1, 2, 5, 10, then 30 minutes by consecutive waits), and a wait for the network SHALL end, whatever the time, on the first tick whose connectivity probe finds a control host reachable. A sign of an outage SHALL be told by the same rules as for a unit's agent run: a strong sign or an HTTP status is taken as it is, a weak sign only by the connectivity probe, and a probe that errors counts as no outage. A wait for the model service by HTTP status SHALL be bounded by `limits.service_unavailable_attempts` consecutive waits, after which the next such failure SHALL count as an ordinary failed attempt. A failure of any other kind SHALL count as before and end a wait. A tick under a network pause SHALL plan no change and make no model call for planning. An edit of `tasks.md`, a successful plan and `abk replan --forget` SHALL end a wait.

#### Scenario: A planner call fails with a network outage

- **GIVEN** a change with one failed attempt and a planner call that ends on a name that could not be resolved
- **WHEN** the tick plans it
- **THEN** its attempts are still one, it is recorded as waiting for the network with the time of the next try, and no unit is stored

#### Scenario: Three outage failures in a row

- **GIVEN** a change that has never been planned and three planner calls in a row, each after its wait, that end on a network outage
- **WHEN** the third is recorded
- **THEN** its attempts are still what they were before the first, and it is not given up

#### Scenario: An ordinary planner failure still counts

- **GIVEN** a planner call that ends in a failure with no sign of an outage
- **WHEN** the attempt is recorded
- **THEN** the attempts rise by one, the reason is kept and no wait is recorded

#### Scenario: An ordinary failure ends a wait

- **GIVEN** a change recorded as waiting for the network and a next planner call that fails for another reason
- **WHEN** it is recorded
- **THEN** the wait is gone, the attempts rise by one and the reason is kept

#### Scenario: A weak sign with the API host reachable

- **GIVEN** a planner call that ends on a refused connection while the probe reaches the host it called
- **WHEN** the attempt is recorded
- **THEN** it counts as an ordinary failed attempt and no wait is recorded

#### Scenario: The network is back

- **GIVEN** a change waiting for the network with its next try still ahead, and a network pause that a tick clears because a control host connects
- **WHEN** the tick plans
- **THEN** the change is planned on that tick and the wait is gone from its record

#### Scenario: The backoff elapses

- **GIVEN** a change waiting for the model service whose next try has passed
- **WHEN** a tick plans
- **THEN** the change is planned again, and a success removes the wait and keeps the attempts it had

#### Scenario: A change that waits is not asked about

- **GIVEN** a change waiting with its next try ahead and no other change to plan
- **WHEN** a tick decides whether to ask the usage guard
- **THEN** planning is not counted as work to do and no model call is made for it

#### Scenario: A tick under the network pause plans nothing

- **GIVEN** a network pause and a probe that reaches no control host, and a change that has never been planned
- **WHEN** a tick runs
- **THEN** no planner call is made and no wait or attempt is recorded

#### Scenario: A service outage is bounded

- **GIVEN** `limits.service_unavailable_attempts` of 3 and a change whose planner call ended on a 529 three times in a row
- **WHEN** a fourth call ends on a 529
- **THEN** it counts as a failed attempt with its reason and the wait ends

#### Scenario: A rate limit keeps its own path

- **GIVEN** a planner call that ends on a 429 usage or rate limit
- **WHEN** the attempt is recorded
- **THEN** it is treated as before and is not recorded as a wait

### Requirement: A change waiting on an outage is shown as waiting

A bare `abk replan` and `abk status` SHALL show a change whose plan waits for the network as waiting for the network and one whose plan waits for the model service as waiting for the model service, each with the time it began and the time of the next try and the attempts as they stand, and neither as failing or given up. `abk replan` of such a change SHALL plan it at once, whatever the wait, and when the outage is still on SHALL say it is waiting for the network or for the model service, that no attempt was used and when the next try is, and not say the plan failed. `abk replan --failed` SHALL select it. A record spent before this requirement SHALL still read as given up.

#### Scenario: The listing says waiting

- **GIVEN** a change whose plan waits for the network
- **WHEN** an operator runs `abk replan` with no selector
- **THEN** its line says it is waiting for the network, with the time of the next try and its attempts, and not `failing` or `given up`

#### Scenario: The status says waiting

- **GIVEN** a change whose plan waits for the model service
- **WHEN** an operator runs `abk status`
- **THEN** it is listed as waiting for the model service with the next try, not as failing and not as waiting for the network

#### Scenario: Replan of a change waiting on the network

- **GIVEN** a change whose plan waits for the network and an outage that is still on
- **WHEN** an operator runs `abk replan` for it
- **THEN** one planner call is made, the output says the change is waiting for the network and that no attempt was used, and it does not say the plan failed

#### Scenario: Replan after the outage

- **GIVEN** a change whose plan waits for the network and a network that is back
- **WHEN** an operator runs `abk replan` for it
- **THEN** the change is planned and its record no longer waits

#### Scenario: A spent plan from before

- **GIVEN** a record with its attempts used up and no wait
- **WHEN** an operator runs `abk replan` with no selector
- **THEN** its line says it is given up and `abk replan --failed` plans it again

### Requirement: A unit waits for all but one of its unrelated open parents

A unit's open parents SHALL be its dependencies in its own repository that are in review, looking through a satisfied dependency to what it
was built on. Two open parents SHALL be related when one is reachable from the other through dependencies, and a unit's unrelated open parents
SHALL be those that no other open parent builds on. A unit that has never started and has two or more unrelated open parents SHALL NOT be
ready: it SHALL wait for all of them but one, and SHALL be ready once at most one remains, the others having merged, been closed or been
satisfied with their work landed. The one it does not wait for SHALL be its base: the unrelated open parent with the greatest stack depth, a
tie going to the one later in plan order. When the open parents form a chain, the unit SHALL be built on the newest, the one that builds on
the others, whatever order its dependencies are listed in. No branch SHALL be made by combining the branches of several parents. A
dependency in another repository SHALL keep waiting for a merge as before and SHALL NOT count as an open parent.

#### Scenario: Two sibling parents in review

- **GIVEN** a unit that has not started and depends on two units of its repository that are both in review, neither built on the other
- **WHEN** the scheduler works out what is ready
- **THEN** the unit is not ready, and it waits for the one of the two that is not its base: the shallower, or for equal depth the earlier in plan order

#### Scenario: One of the siblings merges

- **GIVEN** a unit waiting for one of two sibling parents
- **WHEN** that parent merges, is closed, or is satisfied with its work landed
- **THEN** the unit is ready, and its base is the branch of the other parent

#### Scenario: Three sibling parents

- **GIVEN** a unit that has not started and depends on three unrelated open parents
- **WHEN** the scheduler works out what is ready
- **THEN** it waits for two of them, and the one that is not named is its base

#### Scenario: A chain of parents

- **GIVEN** parent B built on parent A, both in review, and a unit that depends on A and on B
- **WHEN** the scheduler works out what is ready
- **THEN** the unit is ready and its base is B, whichever order its dependencies list A and B in

#### Scenario: A diamond

- **GIVEN** two sibling units in review that were both built on one root, and a unit that depends on both siblings
- **WHEN** the scheduler works out what is ready
- **THEN** it behaves as for two sibling parents, and the root is never named as something it waits for

#### Scenario: A satisfied parent is looked through

- **GIVEN** a unit that depends on a satisfied unit and on another unit in review, and the satisfied unit was built on an in-review unit that is not built on the other
- **WHEN** the scheduler works out what is ready
- **THEN** the unit waits as for two sibling parents, because the satisfied unit is replaced by what it was built on

#### Scenario: A cross-repo parent

- **GIVEN** a unit that depends on one in-review unit of its repository and on a unit of another repository that has not merged
- **WHEN** the scheduler works out what is ready
- **THEN** it waits for the merge of the cross-repository unit as before, and does not wait for a second open parent

#### Scenario: A parent sent back for rework

- **GIVEN** a unit waiting for one of two sibling parents
- **WHEN** the other parent is sent back for rework
- **THEN** the unit waits for it as for any dependency, and is ready again only when it is back in review and the other conditions hold

### Requirement: A unit that has started is not made to wait for a second parent

The wait for a second open parent SHALL apply only to a unit that has not started. A unit that has started SHALL keep the branch it started on,
SHALL NOT be blocked by this rule, SHALL be counted as it is today, and SHALL NOT be requeued or moved off its branch when a parent is
added or appears later.

#### Scenario: A started unit with two open parents

- **GIVEN** a unit with a recorded branch and a pull request whose dependencies are two in-review units, neither built on the other
- **WHEN** the scheduler and the count of units in progress are worked out
- **THEN** the unit waits for nothing it did not wait for before and is counted as before

#### Scenario: A parent added after the unit started

- **GIVEN** a started unit and a replan that gives it a second in-review parent
- **WHEN** the next tick runs
- **THEN** nothing about the unit changes: its branch, base, state and wait are the same

### Requirement: The wait for a second open parent is shown

The status, the ready-queue reason and the graph SHALL show a unit that waits for a second open parent as waiting, naming the parent that must
merge and saying it is the second open parent, and the unit SHALL be blocked as any planned unit that waits on another unit is. The wait SHALL come from
the same answer the scheduler uses, so no consumer reports the unit as ready while the scheduler holds it back.

#### Scenario: The status

- **GIVEN** a unit waiting for one of two sibling parents
- **WHEN** the status is read
- **THEN** it says the unit waits for that parent to merge, as the second open parent

#### Scenario: The graph and the count

- **GIVEN** the same unit
- **WHEN** the graph is drawn and the units in progress are counted
- **THEN** the unit is drawn as blocked, and is counted as any blocked unit is

### Requirement: A change whose groups will give a unit unrelated parents is warned about

`abk tags` and `abk check` SHALL warn, without failing, when a change's task groups can produce a unit with unrelated open parents: an `[acceptance]`
or `[narrow]` group that follows an independent group of its repository, an independent group followed by a later group of its repository, or a
`Needs:` line to a group of another change in the repository of the group's predecessor. The warning SHALL name the group and the shape, in the
form of the other tag warnings, and SHALL NOT change the exit code, the plan or the planner's instructions.

#### Scenario: Acceptance after an independent group

- **GIVEN** a change with an `Independent:` group and an `[acceptance]` group after it, in the same repository
- **WHEN** `abk tags` is run for the change
- **THEN** it prints a warning naming the acceptance group and the shape, and exits as it would without it

#### Scenario: A needs line beside a predecessor

- **GIVEN** a group whose predecessor is in the same repository and which has a `Needs:` line to a same-repository group of another change
- **WHEN** `abk check` is run
- **THEN** it prints a warning naming the group and the shape

#### Scenario: A plain chain is silent

- **GIVEN** a change whose groups form one chain, or whose parallel groups are in different repositories
- **WHEN** `abk tags` is run
- **THEN** no warning is printed

#### Scenario: The planner is told nothing new

- **GIVEN** a change that gets the warning
- **WHEN** it is planned
- **THEN** the planner's prompt and the plan are the same as without this requirement

### Requirement: A restack holds the repository's turn only around its own git commands

A restack SHALL take the repository's turn separately for each phase that writes git state its worktrees share, and SHALL NOT hold
it while an agent edits files. The first phase is the fetch and base check where the restack makes them, the temporary worktree where one
is used, and the rebase up to the point it stops; the second, with no turn held, is the agent's work and the pipeline's reading of the
files it left; the third is the rebase's continuation or its abort, the update of the branch, the rerere cache write and the removal of a
temporary worktree; the push with its lease is a phase of its own. This SHALL hold for a stack move made when a parent merges and for a
unit's own restack inside a run alike, and no phase SHALL take the turn while another is held.

#### Scenario: Another unit's worktree add and push proceed while an agent resolves a conflict

- **GIVEN** a restack that stopped on a conflict and an agent that is still working on it
- **WHEN** another unit of the same repository adds its worktree and then pushes
- **THEN** both complete without waiting for the agent

#### Scenario: A clean move

- **WHEN** a restack applies cleanly
- **THEN** it holds the turn for its git commands only, as before, and no agent is called

#### Scenario: The turn is taken again to finish

- **GIVEN** a conflict the agent has resolved
- **WHEN** the restack continues the rebase and updates the branch
- **THEN** it does so inside the repository's turn, and releases it before the checks, the push and any later agent call

#### Scenario: The same rule for a unit's own restack

- **WHEN** a unit's run restacks its branch onto a moved base
- **THEN** its rebase takes the repository's turn for the same phases, where it took none before

#### Scenario: The agent is rate limited

- **GIVEN** a restack stopped on a conflict
- **WHEN** the agent refuses because a usage window is spent
- **THEN** the rebase is aborted inside the repository's turn, the branch is where it was, and the unit is left to be moved when the window opens

### Requirement: A branch that moved while the agent worked is moved again once, then held

Before it continues a rebase, a restack SHALL read the branch inside the repository's turn and compare it with what it was when the
rebase started. When it differs, the restack SHALL abort the rebase and start the restack again from its first phase, once. When the
branch has moved again the unit SHALL be held planned with the branch and both heads on its record, and nothing SHALL be pushed. This
retry SHALL NOT count as the hold a run is allowed once for a base that moves. A branch that moved on the remote SHALL still be refused by
the push's lease and SHALL NOT be retried.

#### Scenario: The branch moved once

- **GIVEN** a restack whose agent is working and a branch that is moved by another writer
- **WHEN** the restack is about to continue the rebase
- **THEN** the rebase is aborted and the restack starts again from the beginning, once

#### Scenario: The branch moved again

- **GIVEN** a restack that has been started again for a moved branch
- **WHEN** the branch has moved again before it continues
- **THEN** nothing is pushed and the unit is held planned, the record naming the branch and the two heads

#### Scenario: The remote moved

- **WHEN** the push is refused because the remote branch is not the commit last pushed
- **THEN** it is refused as before and the restack is not started again

### Requirement: A restack with no worktree never switches the operator's checkout

A restack of a branch with no worktree of its own SHALL move it in a temporary worktree on no branch, made inside the repository's turn at
the branch's head. The rebase SHALL run there on the detached head and the branch SHALL be moved with a compare-and-swap against the head
it started from, inside the turn. The temporary worktree SHALL be removed inside the turn, and one left by a run that stopped SHALL be
cleaned up inside the turn before the next restack of the branch. A branch that is checked out in another worktree SHALL NOT make the
rebase refuse, and SHALL NOT have its reference moved: the unit SHALL be held planned with the checkout named.

#### Scenario: No worktree

- **GIVEN** a unit whose worktree does not exist
- **WHEN** its branch is restacked
- **THEN** a temporary worktree on no branch is used, the repository's own checkout is not switched, and the temporary worktree is gone afterwards

#### Scenario: The branch is checked out in the operator's checkout

- **GIVEN** a unit with no worktree whose branch is checked out in another worktree
- **WHEN** it is restacked
- **THEN** the rebase runs in the temporary worktree, the branch reference is not moved, and the unit is held planned with the checkout named

#### Scenario: A temporary worktree left behind

- **GIVEN** a temporary worktree left by a restack that stopped
- **WHEN** the same branch is restacked again
- **THEN** it is cleared inside the turn first, and the restack proceeds

### Requirement: A restack never leaves a rebase half finished

Whatever stops a restack between its phases (the agent's refusal, an interruption, a network outage, an error, a check that fails) SHALL
end in the rebase being aborted inside the repository's turn before the stop is reported, so the worktree is left as the branch holds
it. A worktree found with changes it cannot account for SHALL still be refused rather than cleaned.

#### Scenario: An error between phases

- **GIVEN** a restack stopped on a conflict
- **WHEN** the agent step raises an error
- **THEN** no rebase is in progress in the worktree afterwards

#### Scenario: A worktree with a rebase in progress at the next run

- **GIVEN** a worktree left mid-rebase by a process that was killed
- **WHEN** the unit next runs
- **THEN** the worktree is refused as holding changes, as before, and nothing is discarded

### Requirement: A restack takes no build slot and no start admission

Moving a unit onto a changed base, and every step of a run whose only reason to run is that its base moved (a moved-base run), SHALL run
in a lane of its own, outside the workers that build units. It SHALL NOT be refused or delayed by a lack of free build workers, SHALL NOT
be held back by the builds running, SHALL NOT stop or delay a build already running, and SHALL NOT be admitted by the limit on units in
progress: the unit it moves is already in progress or already not, and moving it is not a start. Its only admission SHALL be the lane's own
cap and the usage guard. It SHALL count toward the slot occupancy of its project (the requirement on occupancy below), so that no build
starts while the occupancy is at or above `max_concurrent_stacks`, but it SHALL NOT wait for room under that cap. The port of a conflict the resolver could not settle, a rework of the conflict
kind, unit-test on the result, the review of a resolved move, the check against the base and the push of a rewritten head SHALL be steps of
that run and SHALL run in the lane. Rework that is not about the move (a reviewer's comment, failing checks, e2e-test feedback) and the
build of a new unit SHALL run in a build worker as before.

#### Scenario: Every build slot is busy

- **GIVEN** every build slot is taken by a build and a parent merges, so a child's branch must move onto its new base
- **WHEN** the merge is seen
- **THEN** the child's restack runs at once, and no build is stopped, delayed or given up for it

#### Scenario: A restack running does not reduce the free workers

- **GIVEN** a cap of four, two builds running and a restack running in the lane
- **WHEN** the pass samples its slots
- **THEN** the restack was not refused or delayed for want of a worker, it counts toward the occupancy (three), so the sample's free workers is one and not two, and a unit that is ready starts in the one free slot

#### Scenario: A unit at the limit on units in progress

- **GIVEN** the number of units in progress is at the limit and a unit already in progress has a moved base
- **WHEN** the unit is restacked
- **THEN** it is moved, and no admission is asked of the limit

#### Scenario: A port in the lane

- **GIVEN** every build slot is taken and a unit's resolved move lost some of its own tests, so it is planned for a restack conflict
- **WHEN** the unit is found
- **THEN** its port, unit-test, review and push run in the lane, and no build worker is waited for

#### Scenario: A reviewer's comment during a moved-base run

- **GIVEN** a moved-base run in the lane whose review asks for changes that are not about the move
- **WHEN** the run reaches the rework
- **THEN** the lane does not run it, and the unit waits for a build worker with the rework as its reason

### Requirement: A restack starts when it is seen

A restack SHALL start when the pipeline sees that a unit's base moved, and SHALL NOT wait for the next tick or for a build slot. The base
SHALL be seen by the merge, release and depth handlers when the poller reports the event, by a scan after every poll, every finished
build, every finished restack and every usage pause, and by the end of a run that left its unit planned for a moved base. The scan SHALL
find every unit owed a restack: one that is planned, running with a parked thread, or in review, whose cause is a moved base or a deferred
restack, whose branch does not hold its base, that no run holds, and that is not waiting on another unit. A unit planned for a restack conflict, and
one planned for a deferred restack whose branch already holds its base (a resolved move waiting for its review), SHALL NOT be moved again;
each is owed the moved-base run that follows the move, and the scan SHALL hand it to the lane to run. A restack that could start when a lane worker is free SHALL start before the handler that saw it returns; one that cannot SHALL
start when a worker is free. A unit SHALL be queued at most once, and its new base SHALL be read when its move starts.

#### Scenario: A merge is seen

- **GIVEN** a parent whose pull request has merged and a child stacked on it
- **WHEN** the poller reports the merge
- **THEN** the child's move starts without waiting for a tick

#### Scenario: A unit planned for a moved base

- **GIVEN** a unit a run left planned with a moved base, and no run holding its branch
- **WHEN** the run ends
- **THEN** the unit is moved without waiting for a build slot

#### Scenario: A unit deferred, found by the scan

- **GIVEN** a unit planned with a deferred restack whose branch does not hold its base
- **WHEN** a scan runs after a poll
- **THEN** it is moved

#### Scenario: A unit whose branch already holds its base

- **GIVEN** a unit planned with a deferred restack because its resolved move changed its diff, whose branch holds its base
- **WHEN** a scan runs
- **THEN** it is not restacked again, and its unit-test, review and push run in the lane

#### Scenario: A conflict the resolver could not settle

- **GIVEN** a unit left planned for a restack conflict
- **WHEN** a scan runs
- **THEN** it is not restacked again, and the lane runs its port and what follows

#### Scenario: A unit waiting on another unit

- **GIVEN** a planned unit that waits on a unit that has not merged
- **WHEN** a scan runs
- **THEN** it is not restacked, and is restacked once it is no longer waiting

#### Scenario: A unit owed a restack is not started for it

- **GIVEN** a unit owed a restack while a build slot is free
- **WHEN** the pass looks for what to start
- **THEN** the slot is not given to the unit for its move or for a run that is about the move, and it is started in a build worker only for rework of its own

### Requirement: A separate cap bounds how many restacks run at once

The workspace SHALL configure `limits.max_concurrent_restacks`, the most restacks that run at once across every repository, defaulting to
2. It SHALL be a positive integer, and a value that is not one SHALL be refused when the configuration is loaded, naming the setting. A
restack beyond the cap SHALL wait in the order it was seen, and SHALL start the moment another finishes. The cap SHALL be separate from
`max_concurrent_stacks` and from `max_units_in_progress`.

#### Scenario: A burst of merges

- **GIVEN** the cap is 2 and five merges are seen together, each with a child to move
- **WHEN** the lane takes the work
- **THEN** two restacks run, three wait in the order they were seen, and each starts as one finishes

#### Scenario: The default

- **WHEN** an installation sets no `max_concurrent_restacks`
- **THEN** the cap is 2

#### Scenario: A value that is not a positive integer

- **WHEN** the setting is 0, negative or not an integer
- **THEN** the configuration is refused, naming `max_concurrent_restacks`

#### Scenario: One unit named twice

- **GIVEN** a unit queued for a restack
- **WHEN** a second event names it before it starts
- **THEN** it is queued once, and moves onto the base it has when it starts

### Requirement: A restack never runs under a running step, and a branch is restacked once at a time

A restack SHALL take the unit's branch claim before it does anything, so that no restack runs on a branch a run holds and no two restacks
run on one branch. A unit whose step is running SHALL NOT be restacked: a build that finds its base rewritten SHALL stop at its next
boundary as before, and be moved afterwards. A restack that finds the branch held SHALL leave the unit as it was, and SHALL be tried again
after the holder's run ends. A restack SHALL take the repository's turn for the phases the sibling requirement on restacks names, and SHALL
NOT hold it while an agent edits files.

#### Scenario: A step is running

- **GIVEN** a unit whose build is running a step when its base moves
- **WHEN** the move is seen
- **THEN** nothing is rebased under the step, the build stops at its next boundary, and the unit is then restacked

#### Scenario: Two restacks of one branch

- **GIVEN** a restack running on a branch
- **WHEN** another event names the same unit
- **THEN** no second restack starts on the branch until the first ends

#### Scenario: The turn is taken per phase

- **GIVEN** a restack whose resolver is working and another unit of the same repository that adds a worktree
- **WHEN** both proceed
- **THEN** the worktree add does not wait for the resolver

### Requirement: A restack changes no count of units

A restack SHALL NOT change which units are in progress, blocked or queued. The unit keeps its stored state and cause while it waits for the
lane and while it is moved. Waiting for a restack SHALL NOT make a unit blocked, and a unit that is blocked SHALL NOT be restacked by the
scan. The wait reason of a unit SHALL be the one it has by the existing rules, and a unit waiting for the lane SHALL NOT be given `slot` or
`queue_full` for it. The count of units in progress, the blocked units listed by the queue-full report, and the room the limit leaves SHALL be
what they were without the lane.

#### Scenario: A restack and the queue-full report

- **GIVEN** the limit on units in progress is reached, one started unit is blocked and one is being restacked
- **WHEN** the queue-full report is built
- **THEN** it counts the unit being restacked as in progress, and lists the blocked one as not counted, as it would without the lane

#### Scenario: A freshly unblocked unit owed a restack

- **GIVEN** a unit that was blocked and no longer is, waiting for room under the limit, whose base moved
- **WHEN** the scan runs
- **THEN** it is restacked while it waits for room, and starts when room opens

#### Scenario: A unit waiting for the lane is not blocked

- **GIVEN** an in-review unit queued for a restack
- **WHEN** the count of blocked units is worked out
- **THEN** it is not among them

### Requirement: The status shows restacks as their own line

While the lane has work, or a unit is owed a restack, the status SHALL show the unit as restacking onto its base and SHALL print
`restacks: N running, M waiting`. A restack waiting for a usage pause SHALL be listed with the pause as the reason. The line SHALL be
omitted when nothing runs and nothing waits. A restack SHALL NOT appear in the slot gauges or the `sample` row as a build: the free workers
and the cap SHALL be the build workers', and the lane's two counts SHALL be reported as their own gauges with no unit or change attribute.

#### Scenario: Restacks running and waiting

- **GIVEN** two restacks running and three waiting
- **WHEN** the status is read
- **THEN** it prints `restacks: 2 running, 3 waiting`, and each unit reads restacking onto its base

#### Scenario: Nothing to restack

- **WHEN** no restack runs or waits
- **THEN** the status prints no restacks line

#### Scenario: The sample row

- **GIVEN** a restack running and one build running with a cap of four
- **WHEN** a pass samples its slots
- **THEN** the free workers is three and the row has no field for the lane

#### Scenario: The status of a stopped tick

- **GIVEN** a lane record whose process has gone
- **WHEN** the status is read
- **THEN** the record is ignored and the units are shown by their stored state

### Requirement: `abk tags` says what to pass when it is given nothing

`abk tags` SHALL require either a change name or `--all`. With neither, or with both, it SHALL print one line to
standard error saying what to pass, exit with status 2 and read no change; it SHALL NOT fail with a traceback. Given a
change name alone, or `--all` alone, it SHALL behave as it did before.

#### Scenario: Neither a change nor `--all`

- **WHEN** `abk tags` is run with no argument
- **THEN** it prints `name a change, or pass --all for every change` to standard error, exits 2 and shows no traceback

#### Scenario: Both a change and `--all`

- **WHEN** `abk tags` is run with a change name and `--all`
- **THEN** it refuses with one line on standard error, exits 2 and checks no change

#### Scenario: A change or `--all` alone

- **WHEN** `abk tags` is run with a change name, or with `--all`
- **THEN** it validates that change, or every change, and reports as before

#### Scenario: The help names the flag

- **WHEN** `abk tags --help` is run
- **THEN** the text names `--all`

### Requirement: Priority 0 starts first and may use the emergency lane

Priority 0 SHALL be the most urgent value. A unit of effective priority 0 SHALL start before a ready unit of effective priority 1 or less urgent in the
same class, with ties and classes ordered as for any other value. It SHALL NOT start a unit that is not ready and SHALL NOT stop a running unit. Its only difference from any other value
in what may start is the emergency lane (the requirement of that name): it SHALL NOT otherwise bypass or raise the limit on units in progress, the cap on units running at once, a
project's room, the usage guard, the depth cap, a dependency, a lease, a backoff or any other limit. `abk status`, `abk tags` and the graph page
SHALL show `priority 0` as they show any priority other than 3.

#### Scenario: Priority 0 goes before priority 1

- **GIVEN** one place is free and two ready units that have never run, the later planned of priority 0 and the other of priority 1
- **WHEN** units are chosen
- **THEN** the priority-0 unit starts first

#### Scenario: A prerequisite of a priority-0 unit goes first

- **GIVEN** a ready priority-3 unit that a priority-0 unit waits on, and an older ready priority-1 unit that nothing waits on
- **WHEN** units are chosen with one free place
- **THEN** the prerequisite starts first

#### Scenario: A full queue still holds a priority-0 unit

- **GIVEN** the limit on units in progress is reached and `emergency_extra` is 0, or the project's emergency lane cap is all in use
- **WHEN** a ready unit of priority 0 is considered
- **THEN** it does not start, and it starts first when a place frees

#### Scenario: A full queue does not hold a priority-0 unit that the lane admits

- **GIVEN** the limit on units in progress is reached and `emergency_extra` is 1 with no unit in the lane
- **WHEN** a ready unit of priority 0 is considered
- **THEN** it starts in the emergency lane, as the requirement of that name says

#### Scenario: The display shows priority 0

- **GIVEN** a unit of priority 0 in the store, and a group of priority 0 in a change
- **WHEN** `abk status`, `abk tags` and the graph page are shown
- **THEN** each says `priority 0` for it

### Requirement: The ready queue marks a handoff unit

`abk status` SHALL mark with `(handoff)`, after its reason, each unit in the ready queue that is a handoff unit (a ready unit that has never run and
takes the place a blocked unit frees), so the start order can be explained when a handoff unit stands among units of its own priority. The marker
SHALL NOT appear on a unit that is not a handoff unit, and SHALL NOT change the order or the reason shown.

#### Scenario: Status shows a handoff unit

- **GIVEN** a blocked unit with work, its ready priority-2 prerequisite that has never run, and a ready priority-1 unit that has never run
- **WHEN** the status is read
- **THEN** the ready queue lists the priority-1 unit first, without a marker, and the prerequisite second, as `priority 2 (handoff)`

#### Scenario: No handoff unit

- **GIVEN** no blocked unit that has work and would otherwise count
- **WHEN** the status is read
- **THEN** no line of the ready queue carries the marker

### Requirement: A unit parked on an e2e-test split holds no place, planned or unplanned, whatever its cause field says

A unit in state `planned` or `unplanned` whose `parked_splits` is non-empty (it was parked on a held e2e-test split and has not run its e2e step since)
SHALL NOT count as in progress, whatever work it has (a branch, a pushed commit or a pull request), because it has nothing to run until the split is
released. The rule SHALL NOT depend on the unit's `cause`, which is read from its latest history entry and is lost by a state change that records no
cause: it SHALL hold whether the cause is `split_held` or empty. It SHALL NOT hold when the latest cause is another one (for example `requeued`,
`host_unavailable` or `service_unavailable`), because the unit was then released or interrupted after the park and is on its way to run. A `planned`
unit with the cause `split_held` SHALL still not count, whether or not its `parked_splits` is set. The unit SHALL NOT draw on the room under
`max_units_in_progress`, and `abk status` SHALL leave it out of the count of units in progress and of the line that says the queue is full, and
SHALL list it, planned or unplanned, as parked on its split. A unit whose `parked_splits` has been cleared (a run that resumed it has run its e2e
step), an `unplanned` unit with no parked splits that has a pull request, a branch or a pushed commit, and any unit in state `running` or `in_review`,
SHALL count by the normal rules. When the split is released an `unplanned` unit parked on it SHALL NOT be resumed, requeued or started, because the
plan no longer has it; it SHALL stay uncounted until the plan carries it again as a `planned` unit, and its branch and worktree SHALL be kept.

#### Scenario: A planned unit parked on a split with an empty cause is not counted

- **GIVEN** a `planned` unit with a branch, no pull request, `parked_splits` `["acp"]` and a latest history entry that has no cause
- **WHEN** the count of units in progress is worked out
- **THEN** it is not counted

#### Scenario: An unplanned unit parked on a split with an empty cause is not counted

- **GIVEN** an `unplanned` unit with a branch, no pull request, `parked_splits` `["acp"]` and a latest history entry that has no cause
- **WHEN** the count of units in progress and the room to start are worked out
- **THEN** it is not counted

#### Scenario: Two parked units leave the room whole

- **GIVEN** a limit of 5, four counted units, a planned unit parked on `acp` with an empty cause and an unplanned unit parked on `acp` with an empty cause
- **WHEN** the count of units in progress and the room to start are worked out
- **THEN** the count is 4 and the room is 1

#### Scenario: The status leaves them out and lists them

- **GIVEN** the same units, a ready unit and the split `acp` held
- **WHEN** `abk status` runs
- **THEN** the queue-full line does not appear, the count of units in progress is 4, and both parked units are listed as parked on `acp`

#### Scenario: A planned unit with the cause split_held is as before

- **GIVEN** a `planned` unit with a branch and the cause `split_held`
- **WHEN** the count is worked out
- **THEN** it is not counted

#### Scenario: A unit whose parked splits were cleared counts again

- **GIVEN** a unit that was parked on `acp`, resumed, and whose e2e step ran so that its `parked_splits` is empty, and that has a branch and is not blocked
- **WHEN** the count is worked out
- **THEN** it counts by the normal rules

#### Scenario: A parked unit released and requeued counts when it runs

- **GIVEN** a `planned` unit with `parked_splits` `["acp"]` whose latest cause is `requeued`
- **WHEN** the count is worked out
- **THEN** it counts by the normal rules, because it is no longer waiting for the split

#### Scenario: An unplanned unit with a pull request still counts

- **GIVEN** an `unplanned` unit with a pull request and no parked splits
- **WHEN** the count is worked out
- **THEN** it counts, as before this change

#### Scenario: An unplanned unit with pushed work and no park still counts

- **GIVEN** an `unplanned` unit with a pushed commit, no pull request and no parked splits
- **WHEN** the count is worked out
- **THEN** it counts, as before this change

#### Scenario: Release does not restart it

- **GIVEN** an `unplanned` unit parked on `acp` and `acp` released
- **WHEN** a round runs
- **THEN** the unit is not resumed or started, it stays uncounted, its branch and worktree are kept, and `abk status` still lists it as unplanned and parked on `acp`

#### Scenario: It counts again only when the plan carries it

- **GIVEN** an `unplanned` unit parked on `acp`, `acp` released, and a replan that plans it again
- **WHEN** the unit is planned
- **THEN** the rules for a planned unit apply to it: the round starts it, resuming only its parked split, and it counts once it is running

### Requirement: A replan keeps the splits a unit is parked on

`UnitStore.upsert` SHALL carry `parked_splits`, `parked_sha`, `parked_snapshot` and `parked_attempts` over from the existing record of a unit, as it
does its branch, pull request and feedback, so that a replan that includes the unit, one that leaves it out and sets it `unplanned`, and one that
plans an `unplanned` unit again each leave what it is parked on as it was. A unit parked on a held split SHALL NOT be released by a replan.

#### Scenario: A replan keeps a parked planned unit's splits

- **GIVEN** a `planned` unit parked on `acp` with a `parked_sha`, a `parked_snapshot` and a `parked_attempts` of 1, and a plan that includes it
- **WHEN** the plan is merged into the store
- **THEN** the unit's `parked_splits`, `parked_sha`, `parked_snapshot` and `parked_attempts` are as they were

#### Scenario: A demotion to unplanned keeps them

- **GIVEN** a `planned` unit parked on `acp` and a plan of its change that leaves it out
- **WHEN** the plan is merged into the store
- **THEN** the unit is `unplanned` and its parked fields are as they were

#### Scenario: A unit planned again keeps them

- **GIVEN** an `unplanned` unit parked on `acp` and a plan that includes it
- **WHEN** the plan is merged into the store
- **THEN** the unit is `planned` and its parked fields are as they were

#### Scenario: A replan does not release a held split's unit

- **GIVEN** a `planned` unit with the cause `split_held` parked on `acp`, `acp` held, and a plan that includes the unit
- **WHEN** the plan is merged into the store and the release step runs
- **THEN** the unit is not resumed

### Requirement: A priority-0 unit starts as soon as it is ready, in its own lane with its own cap

For a project, a ready planned unit that is drawing on room (it has never started, or it was blocked, is not now and waits for room) and whose effective priority is 0 SHALL start at the next
tick even when the limit on units in progress and the cap on units running at once are full, after the usage guard, the depth cap, dependencies, leases, backoff and held splits have been
applied. A unit that fits inside the normal limits SHALL start normally and SHALL NOT use the lane cap. Otherwise it SHALL start in the emergency lane when the project's lane use is below
`project_limits.emergency_extra`; the lane use SHALL be the number of priority-0 units currently using the lane (started past the normal limits and not finished), read with the units already
chosen in the round, and SHALL NOT be judged on the occupancy margin. A unit SHALL stay in the lane until it finishes. The lane SHALL be independent of the restack lane: a priority-0 start
SHALL NOT be blocked by lane runs or use any of the restack lane's cap, and lane runs SHALL NOT be blocked by priority-0 units. Every other unit SHALL see the normal limits. The lane SHALL NOT be a
quota or a reservation of a place or a worker. It SHALL be counted for each project. A unit started in the lane SHALL count as in progress and as running like any other. A unit already
in progress (a rework, a resume, a review round) SHALL be unaffected. A priority-0 unit that waits on a dependency is not ready and SHALL use nothing. With `emergency_extra` 0 the rules
SHALL be those without the lane. (The occupancy is today the builds in flight and the units stored running; once the restack lane's occupancy is built it is that figure, and the priority-0
units are part of it.)

#### Scenario: A ready priority-0 unit starts at a full queue and full workers

- **GIVEN** a project with `max_units_in_progress` 5 and `max_concurrent_stacks` 4, five units in progress of which four are running, and `emergency_extra` 1
- **WHEN** a ready priority-0 unit that has never started is considered at the next tick
- **THEN** it starts, and the project has six units in progress and five running

#### Scenario: A ready priority-1 unit does not start in it

- **GIVEN** the same project, with a ready priority-1 unit that has never started and no priority-0 unit
- **WHEN** units are chosen
- **THEN** it does not start, and its wait reason is `queue_full`

#### Scenario: Two priority-0 units with a lane cap of 1

- **GIVEN** the same project and two ready priority-0 units that have never started
- **WHEN** units are chosen
- **THEN** the first in start order starts and the other waits for the lane cap with the reason `queue_full`, and it starts when the first finishes or when the project is below the normal limits

#### Scenario: A lane cap of 0

- **GIVEN** the same project with `emergency_extra` 0
- **WHEN** a ready priority-0 unit is considered
- **THEN** it does not start, exactly as without this requirement

#### Scenario: A priority-0 unit inside the normal limits does not use the lane cap

- **GIVEN** a project with four units in progress of five and one running of four, `emergency_extra` 1, and two ready priority-0 units
- **WHEN** units are chosen
- **THEN** the first starts normally (five in progress) and does not use the lane cap, and the second starts in the lane

#### Scenario: A prerequisite of a priority-0 unit uses the lane

- **GIVEN** a ready priority-3 unit that a priority-0 unit waits on, at the same full project
- **WHEN** units are chosen
- **THEN** the prerequisite starts in the lane and the priority-0 unit stays blocked and uses nothing

#### Scenario: A unit already started is unaffected

- **GIVEN** a full project and a priority-0 unit with a pull request sent back for rework, and a paused priority-0 unit with a branch
- **WHEN** units are chosen
- **THEN** the rework runs as it does at any limit, and the paused unit waits for a normal worker and does not use the lane

#### Scenario: A lane run and a priority-0 start do not block each other

- **GIVEN** four builds running at a cap of four, a moved-base run in the restack lane, `emergency_extra` 1 and a ready priority-0 unit
- **WHEN** units are chosen, and then a base moves while the priority-0 unit runs
- **THEN** the priority-0 unit starts at once, the lane run is admitted at once, neither uses the other's cap, and both count toward occupancy (6/4)

#### Scenario: Other limits still apply

- **GIVEN** a ready priority-0 unit that is beyond the depth cap, under a lease, in a backoff, waiting for a held split, or refused by the usage guard
- **WHEN** units are chosen
- **THEN** it does not start, the lane admitting nothing those rules refuse

### Requirement: A unit in the emergency lane counts toward occupancy and no ordinary new unit starts meanwhile

A unit in the emergency lane SHALL count as in progress and as running, and so toward the project's occupancy, which MAY read above the cap. While the project's count is at or above
`max_units_in_progress` or its occupancy is at or above the cap, no never-started unit that is not of effective priority 0 SHALL start. The lane's unit takes extra room and SHALL NOT make
any, so ordinary starts SHALL wait until the figures fall below the normal limits. A unit that waits for this SHALL read `queue_full` or `slot` as it does for a full queue.

#### Scenario: Nothing else flows in

- **GIVEN** a priority-0 unit started in the lane at a full project, five builds running at a cap of four, and a ready priority-1 unit
- **WHEN** a normal build finishes and units are chosen
- **THEN** the priority-1 unit does not start, because the occupancy is still four, and it starts once the occupancy is below four

### Requirement: A priority-0 unit never holds back a unit that is finishing

A priority-0 start SHALL NOT delay any unit already in progress. A rework, a resume, a review round, a restack and a unit finishing its review SHALL continue as without the lane; a resume SHALL
be held to the free workers counted without the priority-0 units in the lane, so the lane's workers are never a reason for a unit that is finishing to wait.

#### Scenario: A rework is not delayed

- **GIVEN** a priority-0 unit running in the lane at a full project and an in-progress unit sent back for rework
- **WHEN** units are chosen
- **THEN** the rework runs at once

#### Scenario: A resume does not wait for the lane

- **GIVEN** three normal builds and one priority-0 unit in the lane at a cap of four, and a paused unit with a branch
- **WHEN** the round resumes units
- **THEN** the paused unit is resumed as with three builds and no lane unit

### Requirement: The build pool has a thread for the emergency lane

The pool that runs a pass's builds SHALL have `max_concurrent_stacks + emergency_extra` threads for each project that can build, so that a unit started in the lane runs at once and takes no thread
from a unit that is finishing. The restack lane SHALL keep its own workers, apart from the pool, and SHALL add nothing to its size. The number of units that start SHALL be decided by the round,
never by the size of the pool, and a pool larger than the cap SHALL start no unit that would not start without it.

#### Scenario: The extra worker runs

- **GIVEN** four builds in flight at a cap of four and `emergency_extra` 1
- **WHEN** a ready priority-0 unit starts in the lane
- **THEN** its build runs at once beside the four, not queued behind one

### Requirement: The status shows the emergency lane

When a project's room is full or the lane is in use, `abk status` SHALL show it. A queue-full line SHALL say a priority-0 unit may still start while the project's lane use is below
`emergency_extra`, which is above 0. A line `emergency room N/M used by <unit>` SHALL be printed for a project whose lane is in use, N the lane use (the lane cap in use, not a margin) and M
`emergency_extra`, naming the units in the lane. The ready queue SHALL mark `(emergency room)` after the reason of a unit that starts only in the lane, and SHALL NOT change the order or the reason
shown. The unit's wait reason SHALL be `queue_full` for a never-started unit that finds no room. The sample row SHALL keep the normal `limit` and `cap`, and one gauge
`abk.slots.emergency_used` SHALL report the lane use summed over the projects. With `emergency_extra` 0 nothing SHALL be printed or marked for it.

#### Scenario: The lane is free

- **GIVEN** a full queue, `emergency_extra` 1 and no unit in the lane
- **WHEN** the status is read
- **THEN** the queue-full line says a priority-0 unit may still start and no emergency-room line is printed

#### Scenario: The status shows the lane

- **GIVEN** a full queue with one priority-0 unit started in the lane
- **WHEN** the status is read
- **THEN** a line `emergency room 1/1 used by <unit>` is printed beside the queue-full line, which no longer says a priority-0 unit may still start

#### Scenario: A restack run does not use the lane cap

- **GIVEN** four builds and a moved-base run in the restack lane, `emergency_extra` 1
- **WHEN** the status is read
- **THEN** no emergency-room line is printed and the queue-full line says a priority-0 unit may still start

#### Scenario: The ready queue marks the unit

- **GIVEN** a full queue with a ready priority-0 unit that would start only in the lane and a priority-1 unit behind it
- **WHEN** the status is read
- **THEN** the ready queue lists the priority-0 unit first with `(emergency room)` after its reason, and the priority-1 unit without a marker

#### Scenario: Lane 0 prints nothing

- **GIVEN** `emergency_extra` 0
- **WHEN** the status is read
- **THEN** no emergency-room line or sentence appears and the queue-full line reads as before

#### Scenario: The sample row and gauge

- **GIVEN** five builds in a project at a cap of four after a start in the lane
- **WHEN** a pass refreshes
- **THEN** the sample row has `running` 5, `cap` 4 and `free_workers` 0, and `abk.slots.emergency_used` is 1

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

A planned unit with a saved requeue SHALL be delivered that requeue once nothing it waits for is left, whatever its cause says, and a tick SHALL NOT start it for as long as the requeue is saved. A `gated` unit with no saved requeue SHALL NOT be delivered anything. A unit parked for a held e2e-test split SHALL stay stopped until it is released.

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

### Requirement: A moved-base run is a run whose only reason is that the base moved

A run SHALL be a moved-base run when the unit has commits on its branch, is not held by a person, a lease or another run, is not waiting
on another unit, and has no rework input of its own, and its stored cause is a moved base, a deferred restack or a restack conflict, or it
was sent back by the host reporting its pull request as conflicting. A unit held by a run that found its base moved twice SHALL be one. A
unit has rework input of its own when it has saved feedback from a review, a failing check or a test run that is not the feedback of the
conflict, unless review has since approved the branch's head; answered feedback SHALL be cleared as the run starts, and feedback that
names the conflict SHALL NOT be rework input. A run that is not a moved-base run SHALL be a build and run in a build worker; the lane
SHALL still move such a unit as before.

#### Scenario: Each cause

- **GIVEN** units with commits whose causes are a moved base, a deferred restack, a restack conflict, and a conflict sent back
- **WHEN** each is judged
- **THEN** each is owed a moved-base run

#### Scenario: A second find of a moved base

- **GIVEN** a unit a run held planned because its base moved twice in the run
- **WHEN** it is judged
- **THEN** it is owed a moved-base run

#### Scenario: A reviewer's feedback is still to be answered

- **GIVEN** a unit with saved review feedback that no approval covers and a moved base
- **WHEN** it is judged
- **THEN** it is not owed a moved-base run, the lane moves it as before, and it waits for a build worker for its rework

#### Scenario: Answered feedback

- **GIVEN** a unit with saved review feedback whose branch head review has since approved, and a moved base
- **WHEN** its run starts
- **THEN** the feedback is cleared, the run is a moved-base run, and the rework step is not run for it

#### Scenario: A unit with no commits

- **GIVEN** a planned unit with no commits whose base changed
- **WHEN** it is judged
- **THEN** it is a build, not a moved-base run

#### Scenario: Held by a person, a lease or another run

- **GIVEN** a unit held, leased or with its branch held, whose base moved
- **WHEN** it is judged
- **THEN** it is not owed a run

### Requirement: A moved-base run holds a lane worker for its whole length

The lane SHALL run a moved-base run in one of its workers, with the unit's branch held, from the move until the unit waits for review, is
held, fails, is satisfied, is handed back, or is interrupted. The run SHALL run as a build worker's run does, in the unit's own session
where it has one, with its own run log, and SHALL end as a build worker's ends (a usage pause pauses the pass, an unreachable network
parks the unit, an error fails it). It SHALL NOT take a build worker from the pool and SHALL NOT be refused or delayed by a lack of free
build workers; it SHALL be admitted by the lane's own cap (`project_limits.max_concurrent_restacks`, for the unit's project) and the usage
guard alone, in the order the runs were seen, while it SHALL count toward slot occupancy once it runs (the requirement on occupancy below).
It SHALL NOT change the limit on units in progress, since the unit is the one already in progress. A run that was interrupted by a lost process or a usage pause SHALL be resumed by the lane and SHALL NOT be started by a build
worker.

#### Scenario: Every build worker is busy

- **GIVEN** every build worker is running and a unit owed a moved-base run
- **WHEN** the run is handed over
- **THEN** it starts in the lane at once, no build is stopped or delayed, and the run is not refused for want of a free worker

#### Scenario: Free workers fall as the run counts

- **GIVEN** a cap of four, one build running and a moved-base run in the lane, the unit stored as running
- **WHEN** the pass counts its workers and samples its slots
- **THEN** the occupancy is two, the free workers is two, and a ready unit starts in a free worker

#### Scenario: The lane's own cap

- **GIVEN** a lane of 2 and three units owed a moved-base run
- **WHEN** they are handed over
- **THEN** two runs are in the lane, the third waits in the order seen and starts when one ends

#### Scenario: The limit on units in progress

- **GIVEN** the number of units in progress is at its limit and a unit already in progress owed a moved-base run
- **WHEN** the run starts
- **THEN** it starts, and the number in progress is as it was

#### Scenario: A clean move needs no run

- **GIVEN** a unit in review whose approved head moves cleanly onto its base with an unchanged diff
- **WHEN** the lane moves it
- **THEN** unit-test and the push of the stack move are all it does, and no run is made

#### Scenario: The move is not the end

- **GIVEN** a move that needed the resolver and changed the diff
- **WHEN** the lane has moved the unit
- **THEN** the same lane worker goes on into unit-test and the review of the result, and does not leave the unit for a build worker

#### Scenario: A lost process

- **GIVEN** a moved-base run whose process was killed in the middle of the review, the unit stored as running with its thread there
- **WHEN** the next tick scans
- **THEN** the lane resumes it at the review, and no build worker is offered it

### Requirement: A moved-base run stops before work that is not about the move, and hands the unit back

A moved-base run SHALL consist of the move, the resolver, the port, a rework whose feedback is the conflict's, unit-test on the result, the
review of the result, the check against the base, the comments step, the push and the pull request step. It SHALL NOT run a rework that
answers a reviewer, a comment or a failing check, SHALL NOT run a fix of failing checks, and SHALL NOT run e2e-test. A unit that reaches
one of them SHALL have finished its current step, SHALL be left planned with the cause `restack_handed_back` and a note naming the step
and the reason, SHALL keep its thread positioned at that step, and SHALL be started from that step by a build worker like any rework; the
lane SHALL NOT continue it. A running pass SHALL let such a unit back in. A handed-back unit whose base moves again SHALL be judged
afresh.

#### Scenario: The review asks for changes

- **GIVEN** a moved-base run whose review of the resolved move answers with changes
- **WHEN** the thread reaches the rework
- **THEN** the lane does not run it; the unit is planned with `restack_handed_back`, the thread at the rework, and the note says the review asked for changes

#### Scenario: A check fails after the port

- **GIVEN** a moved-base run whose unit-test fails after the port
- **WHEN** the thread would fix the checks
- **THEN** the unit is handed back with the thread at the fix of the checks

#### Scenario: A unit whose tests are end-to-end

- **GIVEN** a moved-base run of a unit whose tier is end-to-end, approved by review
- **WHEN** the thread would run e2e-test
- **THEN** the unit is handed back with the thread at e2e-test

#### Scenario: A build worker takes it from the step

- **GIVEN** a unit handed back at the rework
- **WHEN** a build worker takes it
- **THEN** it runs from the rework, the move is not made again, and the lane has no part in it

#### Scenario: The hand-back is not a failure

- **WHEN** a unit is handed back
- **THEN** it is not failed or held, its approval and pull request are as they were, and a running pass lets it back in

#### Scenario: A conflict rework is not handed back

- **GIVEN** a moved-base run whose rework carries the conflict's feedback
- **WHEN** the thread reaches the rework
- **THEN** the lane runs it

#### Scenario: A run that needs nothing else

- **GIVEN** a moved-base run whose move is clean and whose review approves
- **WHEN** the run reaches the push
- **THEN** it pushes and the unit waits for review, with no worker of the build pool used

### Requirement: A moved-base run counts toward slot occupancy, and no build starts at or above the cap

For each project, the slot occupancy SHALL be the number of distinct unit ids among the builds in flight, the moved-base runs currently
running in the lane (a move, or the run that follows it) and the units stored running as the counts already take them. A unit that is
more than one of these (a lane unit that is also stored running, as one left with `restack_conflict` or `restack_deferred` is) SHALL be
counted once. Work waiting in the lane behind `project_limits.max_concurrent_restacks` SHALL NOT be counted until it runs. The free
workers SHALL be `max(0, max_concurrent_stacks - occupancy)`. A moved-base run SHALL start whatever the occupancy is, so the occupancy MAY
exceed the cap, by lane work only. While the occupancy is at or above the cap, no build SHALL start: not a new start and not a resume,
which is every start that `max_concurrent_stacks` gates. The size of the pool of build workers, the lane's admission, the scan for owed runs
and the choice of what the lane runs SHALL NOT read the occupancy. The limit on units in progress SHALL be unchanged, since the unit of a
run is already counted as in progress.

#### Scenario: A run starts when every worker is busy

- **GIVEN** a cap of four and four builds running, and a base moves so a unit is owed a moved-base run
- **WHEN** the run is handed over
- **THEN** it starts at once, and the occupancy reads 5/4

#### Scenario: No new build starts while a run holds the room

- **GIVEN** a cap of four, three builds running and a moved-base run running in the lane, and a ready unit
- **WHEN** the pass looks for what to start
- **THEN** the occupancy is four, the free workers is zero, and the unit is not started, whether it is new or a resume

#### Scenario: A new build starts once the run ends and the occupancy is below the cap

- **GIVEN** a cap of four, three builds running and a moved-base run that has just ended, and a ready unit
- **WHEN** the next pass looks for what to start
- **THEN** the occupancy is three, the free workers is one, and the unit starts in it

#### Scenario: A build does not start over the cap

- **GIVEN** a cap of four, four builds running and two moved-base runs running, so the occupancy reads 6/4
- **WHEN** one build ends and the pass looks for what to start
- **THEN** the occupancy is five, the free workers is zero, and no build starts until the occupancy is below four

#### Scenario: Occupancy counts a unit once

- **GIVEN** a unit that is stored running and is also running in the lane, as one left with `restack_conflict` is, and a unit that is in flight and stored running
- **WHEN** the occupancy is counted
- **THEN** each of them counts once

#### Scenario: Work waiting in the lane is not counted until it runs

- **GIVEN** a lane of 2 with two runs running and a third unit owed one, stored running, queued behind the lane's cap
- **WHEN** the occupancy is counted
- **THEN** it holds the two running units and not the queued one, and when a run ends and the third starts it is counted

#### Scenario: The lane does not read the occupancy

- **GIVEN** an occupancy at or above the cap and units owed a moved-base run within the lane's cap
- **WHEN** the lane admits and scans
- **THEN** it admits them by its own cap and the usage guard only, and the pool of build workers keeps its size

#### Scenario: The limit on units in progress is unchanged

- **GIVEN** the number of units in progress at its limit and a unit already in progress owed a moved-base run
- **WHEN** the run starts and the occupancy is counted
- **THEN** the number in progress is as it was, and the run is counted once in the occupancy

### Requirement: The status shows the whole of a moved-base run as restacking

While a unit's moved-base run is queued or running in the lane, the status and the graph SHALL show the unit as restacking onto its base,
and `restacks: N running, M waiting` SHALL count the run as one restack, running or waiting. The unit SHALL read so for the whole of the
run and not only for the move. The slot gauges (`abk.slots.free`, `abk.slots.idle_with_ready`) and the `sample` row SHALL report the
occupancy, which counts the run: the row's running count MAY exceed its cap, and its free workers is clamped at zero. `abk status` SHALL
print a slots line of the occupancy over the cap, with the number of restacks in the lane, such as `slots: 5/4, 1 restacking`.

#### Scenario: A run in its review

- **GIVEN** a moved-base run in the lane that has reached the review of the result
- **WHEN** the status is read
- **THEN** the unit reads restacking onto its base and the restacks line counts it as running

#### Scenario: A run waiting for a lane worker

- **GIVEN** a lane of 2 with two runs and a third unit owed one
- **WHEN** the status is read
- **THEN** the line reads `restacks: 2 running, 1 waiting`

#### Scenario: A handed-back unit

- **GIVEN** a unit handed back to the build queue
- **WHEN** the status is read
- **THEN** it no longer reads as restacking, and the restacks line does not count it

#### Scenario: The sample row

- **GIVEN** a moved-base run in the lane and one build running with a cap of four
- **WHEN** a pass samples its slots
- **THEN** the free workers is two, the running count is two, and the two gauges read the same occupancy

#### Scenario: The sample row over the cap

- **GIVEN** four builds running and a moved-base run in the lane with a cap of four
- **WHEN** a pass samples its slots
- **THEN** the running count is five, the free workers is zero and not negative, and the gauge `abk.slots.free` is zero

#### Scenario: abk status shows the slots line

- **GIVEN** four builds running and one moved-base run in the lane with a cap of four
- **WHEN** the status is read
- **THEN** it prints `slots: 5/4, 1 restacking`, and with no run in the lane it prints the occupancy over the cap with no restacking count

### Requirement: The planner is shown priorities and the rule for edges between them

The planner's prompt SHALL mark each group heading of the change with its priority, from the group's own line, else the change's default, else
3, and SHALL list each unit already in flight with its stored priority. It SHALL state that a unit depends on another only for code the other
introduces, that a more urgent unit is not made to depend on a less urgent one merely because their groups are adjacent in the tasks, that
independent groups are not chained, and that a unit takes the most urgent priority of the groups it builds. The prompt SHALL be advice; the
check in the next requirement is the guarantee.

#### Scenario: Group headings carry priorities

- **GIVEN** groups with `Priority: 1`, no line, and a change default of 4 with one group at 2
- **WHEN** the prompt is built
- **THEN** the headings read `(priority 1)`, `(priority 3)`, `(priority 4)` and `(priority 2)`, beside any project or built-by mark

#### Scenario: In-flight units carry priorities

- **GIVEN** a started unit of priority 2 and an unstarted unit promoted to 1
- **WHEN** the prompt is built
- **THEN** the lines show `priority 2` and `priority 1`

#### Scenario: The rule is stated

- **WHEN** the prompt is built
- **THEN** it says to depend on a unit only for code it introduces and not to chain adjacent or independent groups

### Requirement: A plan does not make a unit wait on a less urgent unit that has not started without giving a reason

A unit object of the planner's reply SHALL be able to carry `needs_less_urgent`, an object whose keys are ids the unit lists in `depends_on`
and whose values are non-blank strings that say why. A plan that is not an object of that shape SHALL be refused naming the unit. A plan SHALL be
refused when a unit depends on a unit of the plan, or a stored unit, that has not started and whose own priority (the most urgent of its groups'
priorities, not its stored value) is less urgent than the dependent's, and the dependent gives no reason for that edge. The refusal SHALL name
the unit, the edge, both priorities, and say to drop the edge or give the reason, in its first line, and name any further edge after it. An edge
to a unit that has started, or is merged, closed or satisfied, an edge to an equal or more urgent unit and an edge with a reason SHALL NOT be refused.
The refusal SHALL be a planning failure like any other: the attempt is recorded with the reason and the unit ids, the change is planned again by
the next tick within the allowed attempts, the listing of `abk replan` reads `failing n/m: <reason>` and then `given up`, and `abk replan` exits
non-zero when the change did not plan. No raw error SHALL reach the person. The next attempt's prompt SHALL carry the previous attempt's refusal
reason when the recorded plan is for the current `tasks.md`, and SHALL carry nothing after an outage, a failed call or an edit of `tasks.md`.

#### Scenario: An avoidable edge is refused

- **GIVEN** a plan in which the unit for a priority-1 group depends on the unit for a priority-3 group, with no reason
- **WHEN** the plan is checked
- **THEN** it is refused with a first line naming the unit, `app/1`, priorities 1 and 3, and the two ways out

#### Scenario: An edge with a reason is accepted

- **GIVEN** the same plan with `needs_less_urgent` giving a reason for the edge
- **WHEN** the plan is checked
- **THEN** it passes

#### Scenario: Equal and more urgent targets

- **GIVEN** a unit that depends on units of the same or of a more urgent priority
- **WHEN** the plan is checked
- **THEN** it passes

#### Scenario: A started or finished target

- **GIVEN** a priority-1 unit that depends on a stored priority-5 unit that has started, or is merged
- **WHEN** the plan is checked
- **THEN** it passes

#### Scenario: A stored promotion does not hide the edge

- **GIVEN** a stored unstarted unit promoted to 1 whose own groups are priority 3, and a priority-1 unit that depends on it without a reason
- **WHEN** the plan is checked
- **THEN** it is refused

#### Scenario: A malformed reason

- **GIVEN** a `needs_less_urgent` that is not an object, names a unit that is not in `depends_on` or has a blank reason
- **WHEN** the plan is read
- **THEN** it is refused naming the unit

#### Scenario: A refusal is retried and fed back

- **GIVEN** a change whose first plan was refused for an avoidable edge
- **WHEN** the next tick plans it
- **THEN** the prompt ends with the previous refusal reason, and the attempt count is 2

#### Scenario: A change that never satisfies the check

- **GIVEN** 3 allowed attempts and a model that returns the avoidable edge each time
- **WHEN** the change is planned three times
- **THEN** the listing reads `failing 1/3`, `failing 2/3`, then `given up` with the reason, and `abk replan` exits 1

#### Scenario: A priority-1 unit depends on a priority-0 unit

- **GIVEN** a plan in which the unit for a priority-1 group depends on the unit for a priority-0 group that has not started, with no reason
- **WHEN** the plan is checked
- **THEN** it passes, since 0 is more urgent than 1

#### Scenario: A priority-0 unit depends on a less urgent unit

- **GIVEN** a plan in which the unit for a priority-0 group depends on the unit for a priority-1 group (or a priority-3 group) that has not started, with no reason
- **WHEN** the plan is checked
- **THEN** it is refused with a first line naming the unit, `(priority 0)`, the dependency and `(priority 1)` (or 3), and the two ways out

### Requirement: A unit that has not started is promoted to the urgency of the units that wait on it

After a plan and after the `Needs:` lines are linked, each unit that has not started SHALL be given the most urgent of its own priority (from
its groups) and the priorities of every unit that waits on it, directly or through a chain, in any repository, leaving out units that are
`unplanned` or finished and looking through a satisfied one. A started waiter counts with its stored priority and an unstarted one with its own.
When the result is more urgent than the unit's own, the unit SHALL record the waiter that gives it in `promoted_from` (of equally urgent waiters,
the id that sorts first), and otherwise `promoted_from` SHALL be empty. Both SHALL be recomputed at every such pass, so a promotion lapses at the
next pass after the waiter is merged, closed, dropped or loses its edge, and a replan SHALL never leave a unit below what its waiters need. A unit
that has started SHALL NOT be changed: it keeps its priority and its `promoted_from`. `promoted_from` SHALL be left out of the stored record when
empty, and a record without it SHALL read as empty. Setting the priority of an unstarted unit from its groups SHALL clear it.

#### Scenario: A reasoned edge promotes its target

- **GIVEN** an unstarted priority-3 unit that an unstarted priority-1 unit depends on with a reason
- **WHEN** the plan is made
- **THEN** the prerequisite's priority is 1 and `promoted_from` names the dependent

#### Scenario: A declared need promotes every tick

- **GIVEN** a `Needs:` line from a priority-1 group to a stored unstarted priority-3 unit
- **WHEN** the tick links the needs
- **THEN** the unit is promoted to 1 and names the dependent

#### Scenario: Through a chain

- **GIVEN** units A, B and C of priority 5, 3 and 1, each depending on the one before
- **WHEN** promotion runs
- **THEN** A and B are 1 and both name C or the waiter that gives it, and C is unchanged

#### Scenario: A started ancestor keeps its priority

- **GIVEN** a started priority-3 unit that an unstarted priority-1 unit waits on
- **WHEN** promotion runs
- **THEN** its priority and `promoted_from` are unchanged, and its effective priority is 1

#### Scenario: The promotion lapses

- **GIVEN** a promoted unit whose waiter is merged or dropped
- **WHEN** the next tick or replan runs
- **THEN** the unit has the priority of its groups and an empty `promoted_from`

#### Scenario: A replan does not lower it

- **GIVEN** a promoted unit whose change is replanned and the unit planned again with the default priority
- **WHEN** the replan finishes
- **THEN** the unit is promoted again to what its waiters need

#### Scenario: Equal and less urgent waiters

- **GIVEN** a priority-2 unit that only priority-2 and priority-4 units wait on
- **WHEN** promotion runs
- **THEN** it is unchanged and `promoted_from` is empty

#### Scenario: A record without the field

- **WHEN** a stored unit has no `promoted_from`
- **THEN** it reads as empty, and an empty one is left out when written

#### Scenario: A priority-0 waiter promotes a priority-1 or priority-3 prerequisite

- **GIVEN** an unstarted priority-1 unit and an unstarted priority-3 unit that an unstarted priority-0 unit depends on with a reason
- **WHEN** promotion runs
- **THEN** both prerequisites have priority 0, and `promoted_from` names the priority-0 unit on each

#### Scenario: A promotion to 0 is stored and read back

- **GIVEN** a unit promoted to 0
- **WHEN** the store is written and read again
- **THEN** its priority is 0 and its `promoted_from` is the waiter, not empty and not the default 3

#### Scenario: A priority-1 waiter does not promote a priority-0 unit

- **GIVEN** an unstarted priority-0 unit that only a priority-1 unit waits on
- **WHEN** promotion runs
- **THEN** it is unchanged and `promoted_from` is empty

### Requirement: Authoring warns of a group less urgent than a group that depends on it

`abk tags` and `abk check` SHALL warn, and SHALL NOT fail, for each group that is less urgent than a group that depends on it directly, using the
chain the planner draws between a change's groups (an `Independent:` group has no earlier parent and is skipped as the parent of the next, and an
`[acceptance]` or `[narrow]` group depends on every earlier group) and the `Needs:` lines, whose target is read from the other change's tasks. The
warning SHALL give both groups and priorities, say the earlier group will be promoted, and say to give it the dependent's priority or lower
the dependent's. A target that cannot be read SHALL produce no warning and no error. The exit status of both commands SHALL be as it would be
without the warning.

#### Scenario: A less urgent group in the chain

- **GIVEN** group 5 at priority 3 and group 9 at priority 1 that depends on it
- **WHEN** `abk tags` or `abk check` runs
- **THEN** it prints `group 5 (priority 3) is needed by group 9 (priority 1): it will be promoted to 1; give it Priority 1 or lower group 9` and its exit status is unchanged

#### Scenario: An independent group is skipped

- **GIVEN** an `Independent:` group at priority 1 after a group at priority 3
- **WHEN** the change is checked
- **THEN** there is no warning for that pair, and the group after it is compared with the group before it

#### Scenario: An acceptance group

- **GIVEN** an `[acceptance]` group at priority 1 and earlier groups at 3
- **WHEN** the change is checked
- **THEN** each earlier group is named

#### Scenario: A needed group of another change

- **GIVEN** a `Needs:` line from a priority-1 group to a priority-3 group of another change
- **WHEN** the change is checked
- **THEN** a warning names that change and group

#### Scenario: Nothing inverted

- **GIVEN** groups whose dependents are all at least as urgent
- **WHEN** the change is checked
- **THEN** no priority warning is printed

#### Scenario: A group needed by a priority-0 group

- **GIVEN** group 5 at priority 1 and group 9 at priority 0 that depends on it
- **WHEN** `abk tags` or `abk check` runs
- **THEN** it prints `group 5 (priority 1) is needed by group 9 (priority 0): it will be promoted to 0; give it Priority 0 or lower group 9`, and its exit status is unchanged

#### Scenario: A priority-0 group needed by a less urgent group

- **GIVEN** group 5 at priority 0 and group 9 at priority 1 that depends on it
- **WHEN** the change is checked
- **THEN** no priority warning is printed

### Requirement: The graph, the status and the listing show the effective priority and where it comes from

The graph label, the ready queue of `abk status` and the priority line a tick logs SHALL show a unit's effective priority and its source: a
promoted unit as `priority N, promoted from <unit>`, a started unit that a more urgent waiter covers as `priority N, from <unit>`, a unit with a
priority that is not 3 and no source as `priority N`, and a unit at 3 with no source with nothing. The text of the status SHALL be as it was
for the cases it already named.

#### Scenario: The ready queue

- **GIVEN** an unstarted unit promoted to 1 by `app/9`
- **WHEN** `abk status` lists the ready queue
- **THEN** its line reads `priority 1, promoted from app/9`

#### Scenario: A covered started unit

- **GIVEN** a started priority-3 unit that a priority-1 unit waits on
- **WHEN** `abk status` lists the ready queue
- **THEN** its line reads `priority 1, from` that unit

#### Scenario: The graph

- **GIVEN** a promoted unit
- **WHEN** the graph is drawn
- **THEN** its label shows the effective priority and `promoted from` its source

#### Scenario: A priority-0 unit is shown

- **GIVEN** an unstarted unit of priority 0 with no source, and an unstarted priority-3 unit promoted to 0 by `app/9`
- **WHEN** `abk status` lists the ready queue and the graph is drawn
- **THEN** the first reads `priority 0`, the second `priority 0, promoted from app/9`, and neither is read as a unit at the default priority

### Requirement: The planner chooses joins by logical grouping first and priority second

The planner's prompt SHALL tell the planner to choose joins by logical grouping first: to join work that belongs together, that is groups of one
change, or groups or unstarted units of different changes that modify the same or closely related files or modules, and not to join unrelated work
merely because both are small. It SHALL tell the planner that priority is a secondary influence only: among candidates that fit equally well, the
more urgent work is joined first, so that a less urgent item does not take a partner that a more urgent item with similar files could use, and a
priority never overrides a better logical fit and never joins unrelated work. A unit made by a join SHALL keep taking the most urgent priority of
all its groups, so the joined work is an efficiency gain and the unit resolves the most urgent item at that item's priority. This SHALL be guidance
in the prompt only: no check on priority is added, there is no equal-priority requirement and no limit on the gap between priorities, and the
validity checks of `check_joins` SHALL be unchanged.

#### Scenario: Groups of one change that touch the same module are joined before a group of another change

- **GIVEN** two small groups of one change that modify the same module and a small group of another change that modifies a related one
- **WHEN** the prompt is built
- **THEN** its joining paragraph says to join work that belongs together first, groups of one change and groups that touch the same or closely
  related files or modules, and that unrelated work is not joined merely because both are small

#### Scenario: The more urgent work is offered a partner first among equal fits

- **GIVEN** a more urgent unit and a less urgent unit with similar files that would compete for one join partner
- **WHEN** the prompt is built
- **THEN** its joining paragraph says that among equally good fits the more urgent work is joined first and that a less urgent item does not take a
  partner a more urgent one with similar files could use (decided on the prompt text, as the planner's reply is not scripted)

#### Scenario: A priority never joins unrelated work

- **WHEN** the prompt is built
- **THEN** its joining paragraph says that a priority never overrides a better logical fit and never joins unrelated work, and states no priority
  number limit

#### Scenario: The joined unit keeps the most urgent priority

- **GIVEN** a join of a group of priority 1 and a group of priority 4
- **WHEN** the unit's priority is read
- **THEN** it is 1, and the prompt says that a unit takes the most urgent priority of its groups

#### Scenario: The join checks are unchanged

- **GIVEN** a join of two units of different priorities that satisfies every existing rule, and one that breaks a rule
- **WHEN** `check_joins` runs
- **THEN** the first is accepted and the second is refused for that rule alone, and no rule reads a priority

### Requirement: A change to the planner's rules does not replan recorded plans

A recorded plan is keyed by the hash of its change's `tasks.md`, so a change of the planner's prompt, schema or checks SHALL NOT make a recorded
plan stale, and the tick SHALL NOT replan one for it. The promotion of units that have not started SHALL apply to the edges already stored at the
first pass after the change, without a replan. A person SHALL plan a change again with `abk replan <change>` to drop an avoidable edge, and that
SHALL replace only the edges of units that have not started and keep every started unit.

#### Scenario: Nothing is replanned by the build

- **GIVEN** a change planned before the rule and a `tasks.md` that has not changed
- **WHEN** a tick runs
- **THEN** the change is not planned again

#### Scenario: Stored edges are promoted at once

- **GIVEN** a stored edge from an unstarted priority-1 unit to an unstarted priority-3 unit
- **WHEN** the first tick after the rule runs
- **THEN** the prerequisite is promoted to 1

#### Scenario: A replan drops an avoidable edge

- **GIVEN** that change and a model that no longer draws the edge
- **WHEN** `abk replan <change>` runs
- **THEN** the dependent has no such edge, the prerequisite returns to 3, and started units are unchanged

### Requirement: A unit's id comes from the groups it carries, not from the planner

After a plan has passed every check, the program SHALL give each unit of the change being planned the id `<change>/<L>`, `L` being the lowest task group
number of that change the unit carries; groups of other changes a unit carries by a join SHALL NOT count. The `id` a planner reply gives a unit SHALL be
read as a label, valid only inside that reply: a `depends_on` entry that equals a label SHALL be replaced by the id given to that unit, in order and
without repeats, and an entry that equals no label SHALL be left, as a stored unit's id. The label SHALL NOT be stored. A reply that uses `<change>/<n>`
as its labels SHALL be accepted. A label SHALL be unique in the reply. A unit that carries no group of its change SHALL keep its label as its id. A
started unit SHALL never be given another id, and a join SHALL NOT renumber the unit it joins onto.

#### Scenario: The id follows the lowest group

- **GIVEN** a reply whose units carry groups [1, 2], [3] and [4, 5] under the labels `u1`, `u2` and `u3`
- **WHEN** the plan is read
- **THEN** the units are `x/1`, `x/3` and `x/4`

#### Scenario: Different labels, same groups, same id

- **GIVEN** two replans of one change that group the same groups in the same way, the first labelled `u1`, `u2` and the second `a`, `b`
- **WHEN** both are read against the store the first one left
- **THEN** both give the same ids and the second changes no unit's id

#### Scenario: The old form is accepted

- **GIVEN** a reply whose units are labelled `x/7` for groups [3] and `x/9` for groups [4], and the second depends on `x/7`
- **WHEN** the plan is read
- **THEN** the units are `x/3` and `x/4`, and the second depends on `x/3`

#### Scenario: Joined groups do not count

- **GIVEN** a plan unit of `x` for group 5, in a store where an unstarted unit of `y` has taken `x` group 2 by a join
- **WHEN** the plan is read
- **THEN** the unit is `x/5`

#### Scenario: A reference to a stored unit is left

- **GIVEN** a reply in which a unit depends on `x/1`, which is a merged unit and not a label of the reply
- **WHEN** the plan is read
- **THEN** the dependency is still `x/1`

#### Scenario: A split keeps the lower id on the lowest group

- **GIVEN** an unstarted unit `x/3` for groups [3, 4] and a reply with a unit for group 3 and a unit for group 4
- **WHEN** the plan is read
- **THEN** the first is `x/3`, which the plan rewrites in place, and the second is `x/4`

#### Scenario: A join does not renumber

- **GIVEN** an unstarted unit `y/4` that takes `x` group 2 by a join
- **WHEN** the join is stored
- **THEN** the unit is still `y/4`

#### Scenario: A started unit keeps its id

- **GIVEN** a running unit `x/2` for groups [3, 4] and a reply that plans the remaining groups
- **WHEN** the plan is read and stored
- **THEN** `x/2` has the same id, state and groups, and no planned unit is given its groups or its id

### Requirement: A unit with the same groups as a stored unit keeps its id

Before the rule above applies, a planned unit whose set of the change's own groups equals that of a stored unit of the change that has not started
(`planned` or `unplanned`, with no branch, pull request, pushed commit or approval, and not retired) SHALL be given that unit's id, whatever its
number. Each stored unit SHALL be matched to at most one planned unit, the lowest id first, and every match SHALL be made before any id is computed by
the rule. A stored unit that has started SHALL NOT be matched. A second replan of the same groups SHALL change no id.

#### Scenario: A legacy id is kept

- **GIVEN** an unstarted unit `x/4` for groups [3, 4], the id the planner once chose, and a reply that groups [3, 4] in one unit
- **WHEN** the plan is read
- **THEN** the unit is `x/4` and nothing is renumbered

#### Scenario: A match is owed its id

- **GIVEN** an unstarted `x/2` for groups [3, 4] and a reply with a unit for groups [3, 4] and a unit for group 2
- **WHEN** the plan is read
- **THEN** the first is `x/2` and the second does not take it

#### Scenario: Two replans

- **GIVEN** a plan stored by one replan
- **WHEN** the same change is replanned with the same groups
- **THEN** no unit is given a different id, and none becomes `unplanned`

#### Scenario: A started unit is not matched

- **GIVEN** a running unit for groups [3] and a reply that also asks for groups [3] under a label
- **WHEN** the plan is read
- **THEN** the plan is refused for claiming a group a started unit carries, as before, before any id is given

### Requirement: An id that is taken is not given to other work

The id `<change>/<L>` SHALL be used only when it is free: it is not an id of a retired unit, not already given to another unit of the reply, and not the
id of a stored unit unless that unit has not started and no other planned unit of the reply matches its groups, in which case the plan rewrites that unit
in place as a plan does for any id. A merged, closed, satisfied, running, in review, failed, held, retired or `unplanned` unit with work SHALL keep its id
for itself. When the id is not free the unit SHALL be given the smallest free integer greater than the highest task group number of the change and than
the leading integer of every stored id of the change, so the id is always `<change>/<integer>`; the same store and reply SHALL give the same id. A
retired unit's id SHALL never be given again.

#### Scenario: A retired id is skipped

- **GIVEN** a retired unit `x/3` and a reply with a unit for group 3 and the highest group 5
- **WHEN** the plan is read
- **THEN** the unit is `x/6`, never `x/3`

#### Scenario: A started unit holds its id

- **GIVEN** a running unit `x/2` for groups [3, 4] and a reply with a unit for group 2
- **WHEN** the plan is read
- **THEN** the unit is not `x/2`; it is `x/` followed by an integer above 4 and above every stored number, and `x/2` is unchanged

#### Scenario: An unstarted unit with other groups is reused in place

- **GIVEN** an unstarted `x/3` for groups [3, 4] and a reply that leaves it out and has a unit for group 3 alone
- **WHEN** the plan is read and stored
- **THEN** the unit is `x/3`, rewritten by the plan, and no second `x/3` exists

#### Scenario: The fallback is a plain number

- **GIVEN** a merged unit `x/3` and a reply with a unit for group 3
- **WHEN** the plan is read
- **THEN** the id's last segment is an integer, `unit_number` reads it, and the run log, transcript and branch names are formed as for any other id

#### Scenario: A split piece id is not renamed

- **GIVEN** a plan made to split a held unit, whose pieces are named by that request
- **WHEN** the plan is read
- **THEN** the pieces keep the ids the request gives them

### Requirement: The planner is told its ids are labels, and a label cannot stand for a taken unit

The planner prompt SHALL give the reply shape with `"id": "<label>"`, SHALL say that the program assigns each unit's id from its groups, that the label is
the planner's own for one reply, short and unique, that a unit of the reply is referred to by its label in `depends_on` and `needs_less_urgent`, and
that a unit already in flight is referred to by the id shown. A reply with a duplicate label SHALL be refused. A reply with a label that is the id of a
retired unit, or of a stored unit that has started or finished, SHALL be refused naming it, as an invalid plan; a label that is the id of a stored unit
that has not started SHALL be accepted. A join SHALL name stored units only and SHALL pass through unchanged. An excuse in `needs_less_urgent` SHALL be
read by label.

#### Scenario: The prompt

- **WHEN** the prompt is built
- **THEN** it shows `"id": "<label>"`, says the program assigns the ids, and no longer shows `<change>/<n>` as the shape to return

#### Scenario: A duplicate label

- **GIVEN** a reply with two units labelled `u1`
- **WHEN** it is read
- **THEN** it is refused, naming `u1`

#### Scenario: A label that is a started unit's id

- **GIVEN** a running unit `x/2` and a reply that labels a new unit `x/2`
- **WHEN** it is read
- **THEN** it is refused, naming `x/2`

#### Scenario: A label that is a retired id

- **GIVEN** a retired unit `x/3` and a reply that labels a unit `x/3`
- **WHEN** it is read
- **THEN** it is refused as invalid, naming the id

#### Scenario: A join is not rewritten

- **GIVEN** a reply with a join onto a stored unit `y/1` and a unit labelled `u1`
- **WHEN** the plan is read
- **THEN** the join still names `y/1`

#### Scenario: An excuse by label

- **GIVEN** a unit that depends on the unit labelled `u2`, less urgent and unstarted, with `needs_less_urgent` for `u2` and a reason
- **WHEN** the plan is read
- **THEN** it is accepted and the dependency is the id given to `u2`

### Requirement: A same-repo parent that builds nothing does not stop its child

A unit whose stored dependency is a same-repo unit in `BUILDS_NOTHING` (`unplanned` or `retired`, the states in which nothing waits on a unit) SHALL NOT be
stopped between steps, set back from review, or made to wait for room because of that dependency. The step-boundary check of a running build, the
follow pass for a unit in review and the rule that holds a returning unit for room SHALL each skip such a parent, using the same definition of a unit
that builds nothing that the scheduler's wait uses. A same-repo parent that is `planned`, `running`, `failed`, `held` or `closed` SHALL still hold the
child, and one that is `in_review`, `merged` or `satisfied` SHALL still not. A unit the scheduler admits SHALL NOT be put back by a check that reads the
same dependency.

#### Scenario: A running build and a dropped parent

- **GIVEN** a unit that depends on a same-repo unit the plan dropped (`unplanned`)
- **WHEN** the unit is admitted and its build reaches a step boundary
- **THEN** it goes on and is not set back to `planned` with the cause `upstream_went_back`

#### Scenario: A retired parent

- **GIVEN** a unit that depends on a same-repo unit that a person retired
- **WHEN** its build reaches a step boundary
- **THEN** it goes on

#### Scenario: A parent that is still to be built

- **GIVEN** a unit whose same-repo parent is `planned`, `running`, `failed` or `held`
- **WHEN** its build reaches a step boundary
- **THEN** it stops with the cause `upstream_went_back` naming that parent

#### Scenario: A reviewed parent

- **GIVEN** a unit whose same-repo parent is `in_review`, `merged` or `satisfied`
- **WHEN** its build reaches a step boundary
- **THEN** it goes on, as before

#### Scenario: Two parents

- **GIVEN** a unit with two same-repo parents, one `unplanned` and one `planned`
- **WHEN** its build reaches a step boundary
- **THEN** it stops naming the planned parent only

#### Scenario: The scheduler and the check agree

- **GIVEN** any state a parent can be in
- **WHEN** the scheduler says the unit waits on nothing for that parent
- **THEN** the check at a step boundary does not stop the unit for it

#### Scenario: A unit in review under a dropped parent

- **GIVEN** a unit in review whose same-repo parent is `unplanned` and whose branch holds a commit beyond its last pushed head
- **WHEN** the pass that follows predecessors runs
- **THEN** the unit stays in review

#### Scenario: Room for a returning unit

- **GIVEN** a planned unit with work whose same-repo parent was outside review at some point since the unit last changed state and is now `unplanned`
- **WHEN** the scheduler decides whether the unit must wait for room
- **THEN** that parent does not make it wait

### Requirement: A dependency on a unit that builds nothing is dropped when no line declares it

Each tick, a stored dependency of a unit that has not finished and does not itself build nothing, on a unit in `BUILDS_NOTHING`, SHALL be removed when no
`Needs:` line declares it, and the removal SHALL be logged as `<unit>: dropped dependency <parent>: it builds nothing`. An edge to a unit in any other
state, an edge a `Needs:` line declares, and an edge to a unit not in the store SHALL be kept. The removal SHALL change no wait, base or depth, since
those already ignore a unit that builds nothing, and a second tick SHALL find nothing to drop. This SHALL apply to a started unit: it is not a plan, and
it is the one change to a started unit's stored dependencies that does not come from a `Needs:` line.

#### Scenario: A stale edge after a replan renumbers a group

- **GIVEN** a started unit that depends on a unit the replan dropped (`unplanned`) because its group is now carried by another unit
- **WHEN** the tick links `Needs:` lines
- **THEN** the unit no longer depends on the dropped unit, the log says `dropped dependency` with both ids, and the edge to the new carrier is added if a `Needs:` line asks for it

#### Scenario: A retired parent

- **GIVEN** a unit that depends on a retired unit
- **WHEN** the tick links
- **THEN** the dependency is dropped and logged

#### Scenario: An edge to a unit that is still to be built

- **GIVEN** a unit that depends on a `planned`, `in_review`, `merged` or `failed` unit
- **WHEN** the tick links
- **THEN** the dependency is kept

#### Scenario: A declared edge

- **GIVEN** a `Needs:` line whose group is carried by a live unit
- **WHEN** the tick links, with a stale edge to a dropped unit beside it
- **THEN** the declared edge stays and only the stale one is dropped

#### Scenario: A unit with no `Needs:` line

- **GIVEN** a started unit with a stale edge and no `Needs:` line anywhere
- **WHEN** the tick links
- **THEN** the edge is dropped all the same

#### Scenario: Run again

- **WHEN** the tick links a second time
- **THEN** nothing is dropped and nothing is logged

#### Scenario: Nothing waits differently

- **GIVEN** a unit with a stale edge
- **WHEN** the edge is dropped
- **THEN** the unit's wait reason, base and depth are the same as before

### Requirement: A unit put back again and again with the same cause is named as looping

When a unit goes from `running` to `planned` or `held` after a run shorter than `global_limits.bounce_span_seconds` (default 120), the store, in the one
place every state change is written, SHALL raise the unit's bounce count by one when the cause equals that of the previous counted bounce, and otherwise
start it at one for the new cause. The count SHALL be zero after a run of that length or longer, and after the unit reaches review, fails, merges, is
closed, satisfied, unplanned or retired, or is requeued by a person with `abk requeue`; any other write SHALL leave it. The count, its cause and its time
SHALL survive a replan. When the count reaches `global_limits.bounce_limit` (an integer of at least 2, default 3) the tick SHALL log one line naming the
unit, count, span, cause and last note; `abk status` SHALL list a planned unit at or over the limit under `looping:` with its label, count, cause and note;
and the ready queue SHALL mark it `(looping)`. The notice SHALL NOT hold the unit or change scheduling. For the cause `upstream_went_back` the hold's note
SHALL end `held repeatedly by <parent>` once the stored count makes the next such hold reach the limit.

#### Scenario: The third hold by a parent

- **GIVEN** a unit put back twice with the cause `upstream_went_back`, each run a few seconds long
- **WHEN** a third such hold is written
- **THEN** the note ends `held repeatedly by <parent>`, the tick logs the looping line once, and `abk status` lists the unit under `looping:`

#### Scenario: A base that keeps moving

- **GIVEN** a unit put back to `planned` with the cause `base_changed` three times, each run within 120 seconds
- **WHEN** the third is written
- **THEN** the unit is named as looping with the cause `base_changed`

#### Scenario: Stranded three times

- **GIVEN** `reclaim_stranded` reset a unit to `planned` with the cause `requeued` three times, each run under 120 seconds
- **WHEN** the third reset is written
- **THEN** the unit is named as looping with the cause `requeued`

#### Scenario: A long run resets the count

- **GIVEN** a unit with a count of two
- **WHEN** it runs for ten minutes and is put back with the same cause
- **THEN** the count is zero

#### Scenario: Two causes alternating

- **GIVEN** a unit put back with `base_changed`, then `upstream_went_back`, then `base_changed`, then `upstream_went_back`, each run short
- **WHEN** `abk status` is read
- **THEN** the count is one and the unit is not listed

#### Scenario: Quick parks count

- **GIVEN** a unit parked with the cause `host_unavailable` three times, each run after a backoff wait ending within 120 seconds
- **WHEN** the third park is written
- **THEN** the unit is named as looping; a park whose run lasted 120 seconds or more is not counted

#### Scenario: Review, failure or a person's requeue ends the count

- **GIVEN** a unit with a count at the limit
- **WHEN** it reaches review or fails, or a person runs `abk requeue` for it
- **THEN** the count is zero

#### Scenario: A replan

- **GIVEN** a unit with a count of two
- **WHEN** its change is replanned
- **THEN** the count, cause and time are kept

#### Scenario: The settings

- **WHEN** `global_limits.bounce_limit` is set to 1, or `global_limits.bounce_span_seconds` to 0
- **THEN** the configuration is refused

#### Scenario: Visibility only

- **WHEN** the scheduler runs with a unit named as looping
- **THEN** it admits the unit as it would without the count

### Requirement: A unit a replan replaced records the units that carry its groups now

When a unit becomes `unplanned` by a replan, or is found `unplanned` or `retired` with no record of it, the store SHALL record in the unit's `superseded_by`
the ids of the units that carry its groups: every unit other than it, not `unplanned`, `retired` or `closed`, that builds any `(change, group)` pair the
replaced unit built, its own groups and joined ones, in id order. A merged or satisfied unit SHALL be recorded like a live one. The record SHALL be made
in the same write that sets the state. When no unit carries any of its groups the field SHALL stay empty. A field that is not empty SHALL NOT be
overwritten. The field SHALL be left out of the stored record when empty, so a store with no replaced unit reads and writes as before and a store written
before the field reads with it empty. A unit the plan asks for again SHALL lose it. A join SHALL delete the unit it takes in and, in the same write,
repoint `depends_on`, `needs`, `waited_on` and `superseded_by` of every unit from it to the unit that took it in.

#### Scenario: A join of two groups renumbers the unit

- **GIVEN** a change whose unstarted units `x/3` (group 3) and `x/4` (group 4) are replaced by a replan with one new unit `x/5` that carries groups 3 and 4
- **WHEN** the replan is stored
- **THEN** `x/3` and `x/4` are `unplanned`, each with `superseded_by` `x/5`, and the demotion's history entry says `replaced by x/5`

#### Scenario: A split

- **GIVEN** an unstarted unit carrying groups 3 and 4 that a replan replaces with a unit for group 3 and a unit for group 4
- **WHEN** the replan is stored
- **THEN** its `superseded_by` lists both new units

#### Scenario: Nothing carries the groups

- **GIVEN** a replan that no longer contains a group
- **WHEN** the unit that carried it is set `unplanned`
- **THEN** its `superseded_by` is empty and is left out of the stored record

#### Scenario: A merged unit carries them

- **GIVEN** a replaced unit whose groups a merged unit of the same change carries
- **WHEN** the replan is stored
- **THEN** the merged unit is its successor

#### Scenario: A retired unit

- **GIVEN** a unit ended by `abk retire` whose groups a later plan gives to a new unit
- **WHEN** the plan is stored or a tick runs
- **THEN** the retired unit's `superseded_by` is that unit, and a retired unit whose groups nothing carries has none

#### Scenario: The plan asks for the unit again

- **GIVEN** an `unplanned` unit with a successor
- **WHEN** a replan contains the unit
- **THEN** it is planned and its `superseded_by` is empty

#### Scenario: A set field is kept

- **GIVEN** a replaced unit whose successor was itself replaced later
- **WHEN** the store records successors again
- **THEN** the first unit's `superseded_by` is unchanged

#### Scenario: A store from an earlier release

- **GIVEN** a units file with no `superseded_by` anywhere
- **WHEN** it is loaded and written
- **THEN** every unit reads with it empty and the written file has no such key

#### Scenario: A join

- **GIVEN** an unstarted unit taken into another by a join, a started unit that depends on it and a unit whose `superseded_by` names it
- **WHEN** the join is written
- **THEN** the taken unit is gone and the other two name the unit that took it in, once each

### Requirement: A dependency on a replaced unit is read as the units that carry its work

Every reader of a unit's dependencies SHALL read one resolved list, the stored dependencies with each entry that names an `unplanned` or `retired` unit
that has successors replaced by its successors, followed through further replaced units to at most eight links, once each, in order, never the unit
itself. A replaced unit that has no successors, a successor that is missing, and a cycle in the field SHALL stand for the unit named, so the readers that
skip a unit that builds nothing skip it. A merged, satisfied or closed result SHALL be passed on unchanged, to be treated as any finished parent. The scheduler, the stack's base and depth, the build's check at a step boundary, the follow pass, the restack, the wait for room, promotion, the cycle checks, the retire command, the planner's view, the diagram and the graph page SHALL all read it, so none disagrees about what a unit depends on.

#### Scenario: The wait follows the successor

- **GIVEN** a started unit whose stored dependency is a replaced unit and whose successor is `planned`
- **WHEN** the scheduler and the build's check at a step boundary read its dependencies
- **THEN** both name the successor and neither names the replaced unit

#### Scenario: A chain

- **GIVEN** `a` replaced by `b`, `b` replaced by `c`, and a unit that depends on `a`
- **WHEN** its dependencies are read
- **THEN** they are `c`

#### Scenario: A chain longer than the bound

- **GIVEN** ten replaced units in a line and a dependent of the first
- **WHEN** its dependencies are read
- **THEN** the read ends at the eighth link

#### Scenario: A merged successor

- **GIVEN** a dependency on a replaced unit whose successor is merged
- **WHEN** the scheduler reads it
- **THEN** the dependent does not wait for it, as for any merged parent, and the status shows it as covered

#### Scenario: No successor

- **GIVEN** a dependency on a replaced unit with an empty `superseded_by`
- **WHEN** it is read
- **THEN** it names that unit, and the rule for a parent that builds nothing applies to it

#### Scenario: The cycle checks

- **GIVEN** a plan edge that would close a cycle only through the successor of a replaced unit a stored unit depends on
- **WHEN** the plan is checked
- **THEN** the edge is dropped and the cycle is named

### Requirement: A tick repoints a stored dependency on a replaced unit

Each tick after planning, and in `abk replan`, a dependency stored on any unit that has not finished, started or not, that names a replaced unit with
successors SHALL be replaced in place by its live successors. When the unit's `Needs:` lines resolve to some of those successors only those SHALL be
taken; when it has none, every successor SHALL be. A successor that would close a cycle SHALL be refused and logged as a refused `Needs:` is; the rest SHALL be taken, and with none left the stored dependency SHALL stay. The write SHALL be logged `<unit>: dependency <old> is now <new> (replaced by a
replan)`. An edge with no successor SHALL NOT be changed by this requirement; the rule for a stored dependency on a unit that builds nothing applies to
it, and it SHALL come after this one, so an edge that has a successor is repointed and never dropped. A second tick SHALL change nothing.

#### Scenario: A started dependent after a join

- **GIVEN** a running unit that depends on `x/3`, replaced by `x/5`
- **WHEN** the tick links
- **THEN** it depends on `x/5`, `x/3` is gone from its dependencies, and the log says `dependency x/3 is now x/5 (replaced by a replan)`

#### Scenario: A split and a planner edge

- **GIVEN** a unit with a planner dependency on a unit replaced by two units, and no `Needs:` line
- **WHEN** the tick links
- **THEN** it depends on both

#### Scenario: A split and a `Needs:` line

- **GIVEN** a unit whose `Needs: x group 3` line resolves to one of two successors of a replaced unit it still stores
- **WHEN** the tick links
- **THEN** it depends on that successor only

#### Scenario: A merged successor

- **GIVEN** a stored dependency on a replaced unit whose successor is merged
- **WHEN** the tick links
- **THEN** the dependency is the merged unit, and the unit's wait is the same as before

#### Scenario: No successor

- **GIVEN** a stored dependency on a replaced unit with an empty `superseded_by`
- **WHEN** the tick links
- **THEN** this requirement changes nothing, and the dependency is left to the rule for a parent that builds nothing

#### Scenario: A successor that would close a cycle

- **GIVEN** a successor that already waits on the dependent
- **WHEN** the tick links
- **THEN** the log names the cycle, the dependent keeps its stored dependency, and the refusal is not logged again for the same pair

#### Scenario: Run again

- **WHEN** the tick links a second time
- **THEN** nothing is changed and nothing is logged

### Requirement: A wait recorded on a replaced unit follows its successor

A failed unit's recorded wait (`waited_on`) SHALL be judged on the units that stand in for each recorded id. A recorded id that is a replaced unit with
successors SHALL NOT end the wait as a prerequisite that was closed: while a successor is unreviewed the record SHALL name it; when every successor is
reviewed or merged the unit SHALL be requeued as for any wait that ended. A replaced unit with no successors SHALL end the wait as a closed prerequisite
does. The planner SHALL be shown a replaced unit as replaced by its successors, and an unstarted unit's dependencies as the resolved list. History notes, feedback and guidance SHALL stay as written.

#### Scenario: The successor lands

- **GIVEN** a failed unit that was recorded waiting on `x/3`, now replaced by `x/5`, which is in review
- **WHEN** the tick requeues units whose wait ended
- **THEN** the unit is requeued once and no `wait_ended` is recorded

#### Scenario: The successor is still building

- **GIVEN** the same unit with `x/5` planned
- **WHEN** the tick runs
- **THEN** the record names `x/5`, and the unit keeps waiting

#### Scenario: Nothing carries the work

- **GIVEN** a recorded wait on a replaced unit with no successors
- **WHEN** the tick runs
- **THEN** the unit stays failed with `wait_ended` naming it

#### Scenario: The planner's view

- **GIVEN** an `unplanned` unit with a successor and an unstarted unit with a stored dependency on it
- **WHEN** the planner is shown the in-flight units
- **THEN** the first reads `replaced by` the successor, still saying what it built, and the second depends on the successor

### Requirement: The status, the replan report and the graph show a replaced unit with its successor

`abk replan` SHALL report a unit it set `unplanned` as `now unplanned, replaced by <ids>` when it has successors. `abk status` SHALL list, as `replaced:
<unit> by <ids>`, each replaced unit that an unfinished unit's stored dependencies, `needs` or recorded wait still name, which is a pass that has not yet
run. The graph page's unit data SHALL give a replaced unit its successors, and its dependencies SHALL be the resolved list. The diagram SHALL draw an edge
to a replaced unit from its successor.

#### Scenario: The replan report

- **GIVEN** a replan that joins two unstarted units into one
- **WHEN** it prints what changed
- **THEN** each replaced unit is reported as `now unplanned, replaced by` the new unit

#### Scenario: A reference not yet repointed

- **GIVEN** a replaced unit with a successor that a started unit still names
- **WHEN** `abk status` is read before the next tick
- **THEN** one `replaced:` line names the unit and its successor

#### Scenario: The graph data

- **GIVEN** a unit that depends on a replaced unit
- **WHEN** the unit's data is read
- **THEN** its dependencies are the successors, and the replaced unit's data lists them as `replaced_by`

### Requirement: Units replaced before successors were recorded are given them once

Each tick, before linking, the store SHALL give every `unplanned` or `retired` unit with an empty `superseded_by` the successors the current store
computes, in one write, and the tick SHALL log `successors recorded: <n> unit(s)` when it wrote any. A unit nothing carries SHALL stay empty and be computed again later, and a unit that has successors SHALL NOT be written again. A second run SHALL write nothing.

#### Scenario: Two stale dependents

- **GIVEN** an `unplanned` unit with no record whose groups a live unit carries, and two units that depend on it
- **WHEN** the first tick after the release runs
- **THEN** the unit has the live unit as successor, the two are repointed to it in the same tick, and the log says `successors recorded: 1 unit(s)`

#### Scenario: A renumbered legacy unit is given its successor once

- **GIVEN** an `unplanned` unit with no record that an earlier release renumbered, so that a live unit now carries exactly its groups, and a started unit that depends on it
- **WHEN** the first tick after the release runs, and then a second
- **THEN** the first records that unit as the successor and repoints the dependent, and the second writes nothing and logs nothing

#### Scenario: Idempotent

- **WHEN** the tick runs again
- **THEN** the store is not written and nothing is logged

#### Scenario: Nothing carries them

- **GIVEN** an `unplanned` unit whose groups no unit carries
- **WHEN** the tick runs
- **THEN** its field is empty and it is not counted

### Requirement: A replan keeps a rebuilt unit's runtime fields except the one that says it was replaced

A unit that a replan contains SHALL be live, so the record of what replaced it SHALL be empty after the replan, whatever it held; every other field the
replan keeps SHALL be kept as before. A unit that a replan does not contain SHALL keep it.

#### Scenario: Revived

- **GIVEN** an `unplanned` unit with `superseded_by` and a replan that contains it
- **WHEN** the replan is stored
- **THEN** the unit is planned, its record has no `superseded_by`, and its other runtime fields are as they were

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
the environment, an unreachable host, network or service) SHALL be resumed; a saved failure from a unit-test or e2e-test check with feedback
SHALL be reworked from that failure; any other unit SHALL be resumed; and it SHALL NOT start over. A person's recorded guidance SHALL be kept and
SHALL NOT change the mode. The setting `global_limits.wait_end_requeue` SHALL be `auto` (the default), `resume`, `rework` or `off`; `resume` and `rework` SHALL force
that mode (a rework with no saved failure and no guidance resuming), and `off` SHALL leave a failed unit that waits as it is today, requeued by a person only.

#### Scenario: A check failure on real errors

- **WHEN** the unit's saved failure is an e2e-test check failure with feedback and its wait ends
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

### Requirement: A unit stores only its direct dependencies

A unit's stored dependencies SHALL be its direct dependencies: the transitive reduction of its dependencies over the stored graph. A dependency that
another dependency of the same unit reaches through stored dependencies, directly or through any number of units of any state and in any repository,
SHALL NOT be stored. A unit with two dependencies neither of which reaches the other SHALL keep both. Planning (`upsert`), a `Needs:` link, the
repointing of a join and every other write of a unit's dependencies SHALL store the reduced list in the order given. One function, `direct_dependencies`,
SHALL compute it, and no other code SHALL reduce a list of its own. A stored cycle SHALL NOT make the function loop or drop a dependency of the cycle.

#### Scenario: A chain with a redundant ancestor

- **GIVEN** unit B depending on A, and a plan that makes unit C depend on both B and A
- **WHEN** the plan is stored
- **THEN** C stores B alone

#### Scenario: A diamond keeps both parents

- **GIVEN** units B and C that each depend on A, and a unit D that depends on B, C and A
- **WHEN** D's dependencies are stored
- **THEN** D stores B and C, and not A

#### Scenario: Unrelated dependencies are all kept

- **GIVEN** a unit that depends on two units, neither of which reaches the other
- **WHEN** its dependencies are stored
- **THEN** it stores both, in the order given

#### Scenario: Through a merged unit and across repositories

- **GIVEN** A in one repository, B in another that depends on A, B merged, and C that depends on both
- **WHEN** C's dependencies are stored
- **THEN** C stores B alone

#### Scenario: A stored cycle

- **GIVEN** two units that depend on each other
- **WHEN** their dependencies are reduced
- **THEN** the call returns, and both dependencies are kept, because each is reached only through the other

#### Scenario: One function

- **WHEN** the writers of a unit's dependencies and the views that show them are read
- **THEN** each calls `direct_dependencies`, and none holds a reduction of its own

### Requirement: The existing store is reduced once, through the store's own methods

The first tick or `abk replan` after this change is built SHALL read the stored units and, for each unit that stores a dependency another of its
dependencies reaches, record the reduced list through `set_dependencies`, logging the unit and the dependencies removed. It SHALL NOT edit the store
file by any other route. A second tick or replan SHALL change nothing. It SHALL run only once an acceptance or narrow unit's wait is computed at run
time, so no unit loses a wait it had, and it SHALL NOT change a unit's state, branch, pull request or history other than its dependencies.

#### Scenario: A store with redundant edges

- **GIVEN** a store in which a unit stores four dependencies, three of them reached by the fourth
- **WHEN** a tick runs
- **THEN** the unit stores the fourth alone, the log names the three removed, and nothing else of the record changed

#### Scenario: Run again

- **GIVEN** a store that has been reduced
- **WHEN** a second tick or a replan runs
- **THEN** no write is made and nothing is logged for it

#### Scenario: A started unit

- **GIVEN** a running unit that stores a redundant dependency
- **WHEN** the reduction runs
- **THEN** its list is reduced, its state and branch are untouched, and its base is the one it had

### Requirement: An acceptance or narrow unit waits for every earlier unit of its change at run time

A unit whose flag is `acceptance` or `narrow` SHALL wait for every earlier unit of its own change, computed from the change's units each time and not
from stored dependencies. For each earlier unit, in the unit's repository the wait SHALL hold until it is in review, merged or satisfied, and in another
repository until it has merged or been satisfied with its work landed, exactly as a dependency on it would; a unit the plan dropped SHALL NOT hold it.
The same earlier units SHALL stop a running build of the unit when one of them goes back, and SHALL send the unit back from review while one of them
is changing its branch, as the unit's stored parents do. The rule SHALL add waits only: it SHALL NOT change the unit's base, its depth or the open
parents it waits for. A unit whose record has no flag SHALL follow the chain as any other unit does.

#### Scenario: An earlier unit sent back while its successor is in review

- **GIVEN** an acceptance unit whose stored dependency is the last unit of a chain, that last unit in review, and a unit two places before it that is sent back
  for rework
- **WHEN** the scheduler works out what is ready
- **THEN** the acceptance unit is not ready and waits for the unit sent back

#### Scenario: A running acceptance unit stops

- **GIVEN** a running acceptance unit and an earlier unit of its change, not among its stored dependencies, that goes back to planned
- **WHEN** the build checks its upstream
- **THEN** it stops with the cause upstream went back, naming that unit

#### Scenario: An acceptance unit in review follows

- **GIVEN** an acceptance unit in review and an earlier unit whose branch is changing
- **WHEN** the pass follows predecessors
- **THEN** the acceptance unit is set back to planned with that unit named

#### Scenario: An independent unit counts as an earlier unit

- **GIVEN** a change of a chain of two units, an independent unit and an acceptance unit that stores the second unit and the independent unit
- **WHEN** the scheduler works out what is ready while the independent unit is not yet in review
- **THEN** the acceptance unit waits for it and for the chain's units, the same as with every edge stored

#### Scenario: The live store

- **GIVEN** the acceptance units of a recorded store, reduced
- **WHEN** their waits are worked out
- **THEN** each waits for the same units as with the unreduced list

#### Scenario: A unit with no flag follows the chain

- **GIVEN** a unit that depends on a unit in review, whose own parent is sent back, and that has no flag
- **WHEN** the scheduler works out what is ready
- **THEN** it is ready, as a plain chain's unit is

#### Scenario: The base is untouched

- **GIVEN** an acceptance unit that waits for an earlier unit that is in review and not among its stored dependencies
- **WHEN** its base is worked out
- **THEN** it is the base the stored dependencies give

### Requirement: Every other unit follows the chain

A unit that is not an acceptance or narrow unit SHALL NOT wait for, stop for or be sent back by a unit it reaches only through another dependency. A
unit sent back for rework SHALL reach the units built on it through the chain: each parent restacks onto the reworked branch, and each unit in review
follows its predecessor. A parent whose restack is deferred or conflicted, and a thread that declines the move, SHALL leave the units behind it as they
are, as for a plain chain today.

#### Scenario: A grandparent sent back

- **GIVEN** units A, B and C in a chain, B and C in review, and A sent back for rework
- **WHEN** the passes run
- **THEN** B is set back to planned as its predecessor changes, and C follows B, with no wait of C on A

#### Scenario: A grandparent closed

- **GIVEN** a chain A, B, C with A closed and B and C in review
- **WHEN** the scheduler works out what is ready
- **THEN** C is not held by A

#### Scenario: A deferred restack

- **GIVEN** the chain with B's restack deferred
- **WHEN** the passes run
- **THEN** C is not moved ahead of B, and the gap is the one a plain chain has

#### Scenario: A merge restacks once

- **GIVEN** A merging with B and C stacked on it in a chain
- **WHEN** A's children are released
- **THEN** B is moved onto the trunk, and C, which sat on B's branch, is not moved a second time off A

#### Scenario: A branch is removed when its dependents are done

- **GIVEN** a merged unit with one direct dependent and a unit built on that dependent
- **WHEN** its branch is considered for removal
- **THEN** only the direct dependent is probed and the branch stays while it is held or not moved

### Requirement: A started unit's base does not depend on the order of its dependencies

A unit that has started SHALL build on the open parent an unstarted unit would: the unrelated open parent with the greatest stack depth, a tie going to
the later in plan order, and the same unit SHALL be the predecessor a thread is told it moves onto. Neither SHALL depend on the order the unit's
dependencies are listed in, and a dependency added later SHALL NOT change either.

#### Scenario: A later-added ancestor

- **GIVEN** a running unit that depends on B, with B built on A, and a `Needs:` line that adds A after B
- **WHEN** the base and the predecessor are worked out
- **THEN** both are B, as before the line

#### Scenario: The list is reordered

- **GIVEN** a started unit whose dependencies list A and B, B built on A
- **WHEN** the list is stored as B then A and as A then B
- **THEN** the base and the predecessor are B in both

#### Scenario: An unstarted unit

- **WHEN** the base of a unit that has not started is worked out
- **THEN** it is what it was

### Requirement: The planner is asked for the units a group exercises

The planner's instructions SHALL ask that an `[acceptance]` or `[narrow]` group's unit name the units it exercises, or removes the old half of, and SHALL
NOT ask that it depend on every unit; the instructions for an independent group SHALL say that the unit still waits for the independent unit. A plan
that does not reach every such unit SHALL be refused as before. `plan_units` SHALL give such a unit the units it exercises: the tail of its chain and
every independent unit, and not every earlier unit. A unit the planner is shown as in flight SHALL list its direct dependencies.

#### Scenario: The prompt

- **WHEN** the planner's instructions are built
- **THEN** the acceptance rule names the units exercised and does not say every unit, and the independent rule still says the unit waits for the independent one

#### Scenario: An acceptance unit after independent groups

- **GIVEN** a chain of three units, an independent unit and an acceptance group
- **WHEN** the groups are made into units
- **THEN** the acceptance unit depends on the third unit and the independent unit, and on no other

#### Scenario: A plan that misses a unit

- **GIVEN** an acceptance unit that reaches neither a unit it exercises nor anything that builds on it
- **WHEN** the plan is checked
- **THEN** it is refused naming the unit, as before

#### Scenario: In-flight lines

- **GIVEN** a stored unit that lists a redundant ancestor
- **WHEN** the planner is shown it
- **THEN** its line names its direct dependencies

### Requirement: Every view shows a unit's direct dependencies

The graph page, the Dependencies list of a unit's page, the waiting lines of `abk status`, the "Merge ... first" list of a pull request's body and the
lines a replan prints about a unit's dependencies SHALL all be made from `direct_dependencies`, so they SHALL name the same dependencies for the same
unit. The graph page SHALL draw a merged or satisfied parent only when an edge to it is kept, and SHALL draw no edge for a `Needs:` the chain implies.
A body SHALL name the unmerged direct parents, and a parent's own body names what it waits for.

#### Scenario: The same edges in every view

- **GIVEN** a chain A, B, C with C's stored list still holding A
- **WHEN** the graph, the unit's page, `abk status` and C's pull request body are made
- **THEN** each names B and none names A

#### Scenario: A merged parent

- **GIVEN** a unit that depends on a merged unit only through another dependency
- **WHEN** the graph is drawn
- **THEN** the merged unit is not drawn for it, and one that a kept edge reaches is drawn

#### Scenario: A replan line

- **GIVEN** a replan after which a unit's stored dependencies differ
- **WHEN** it prints what changed
- **THEN** it names the changes in the direct dependencies

#### Scenario: A thick edge is kept

- **GIVEN** a `Needs:` that is a direct dependency of the unit
- **WHEN** the graph is drawn
- **THEN** its edge is thick and labelled `needs`

### Requirement: A Needs line the chain implies is recorded and not linked

The stored `needs` of a unit SHALL name every unit its `Needs:` lines name, kept apart from its dependencies, and SHALL change only when the lines
do. A target the unit already reaches through its dependencies SHALL NOT be added as a dependency, now or on a later tick; a target it does not reach
SHALL be added and the dependencies stored reduced. A target that would close a cycle SHALL be refused as before, judged by reachability.

#### Scenario: Linked once

- **GIVEN** a unit that depends on a unit that already depends on the unit its `Needs:` names
- **WHEN** ten ticks run
- **THEN** the unit's dependencies never gain that unit, no line says it is now depending on it, and its `needs` names the target

#### Scenario: A target that reaches a listed dependency

- **GIVEN** a unit that depends on A and a `Needs:` that names B, which depends on A
- **WHEN** the line is linked
- **THEN** the unit stores B alone, and `needs` names B

#### Scenario: A line removed

- **WHEN** a `Needs:` line is removed
- **THEN** the unit's `needs` no longer names it on the next tick

#### Scenario: A cycle is refused

- **GIVEN** a `Needs:` line that names a unit that depends on the unit itself, directly or through others
- **WHEN** it is linked
- **THEN** it is refused as before, with the cycle logged once

### Requirement: A `Needs:` line has a plain kind and a merge kind

A `Needs: <change> group <n> — why` line SHALL be a plain dependency: a planned dependent in the parent's repo is released once the parent unit is in review,
merged or satisfied and builds on the parent's branch, and a dependent in another repo is released once the parent has merged. A line with the single word
`merged` straight after the group number, `Needs: <change> group <n> merged — why`, SHALL be a merge dependency. The word SHALL mean that only when it
follows the group number directly; anywhere else in the line it is part of the reason. `abk tags` and `abk check` SHALL accept a merge line without a
deprecation warning, SHALL keep refusing a `Needs:` of either kind on a group of the change's own, and SHALL keep warning of a `Needs:` that the
chain already implies only as they did. `link_needs` SHALL record the kind on the dependent unit as `merge_needs`, a subset of its `needs`, recomputed from
`tasks.md` every tick, so a removed line or a line changed back to plain removes the mark. A target named by a plain and a merge line of one group SHALL
be a merge dependency.

#### Scenario: A plain line is unchanged

- **GIVEN** a planned unit in repo A with `Needs: parent group 1 — why` and a parent unit in repo A that is `in_review`
- **WHEN** a tick plans and starts units
- **THEN** the dependent is startable on the parent's branch, with no wait, exactly as before this change

#### Scenario: A merge line is accepted without a warning

- **GIVEN** a group with `Needs: parent group 1 merged — the tick must run the fix`
- **WHEN** a person runs `abk tags` or `abk check` on the change
- **THEN** no deprecation warning is printed, the reason read is `the tick must run the fix`, and the dependent unit's `merge_needs` holds the parent unit after the next tick

#### Scenario: The word elsewhere is part of the reason

- **GIVEN** `Needs: parent group 2 — merged later`
- **WHEN** it is read
- **THEN** it is a plain dependency whose reason is `merged later`

#### Scenario: A merge line on the change's own group is an error

- **GIVEN** `Needs: this-change group 1 merged` inside group 2 of `this-change`
- **WHEN** `abk tags` runs
- **THEN** it reports the error it reports for any own-group `Needs:` and the line is not applied

#### Scenario: The mark follows the file

- **GIVEN** a unit linked with a merge dependency
- **WHEN** the word `merged` is deleted from the line and a tick runs
- **THEN** `merge_needs` no longer names the parent and the dependency is plain

### Requirement: A merge dependency holds a start until the parent is merged and its merge is in the running code

A planned unit with a merge dependency SHALL NOT start while the parent unit is not `merged`, or `satisfied` with its work landed; a parent in review,
rework, failed or held holds it. In addition, when the parent's repository is the checkout the running pipeline's code was loaded from, the unit SHALL NOT
start until that code contains the parent's merge. A tick SHALL record, as it starts and before its first round, a number, its start time and the head
commit of that checkout; the pipeline SHALL record, when a unit is first seen merged, the merge commit the code host reports and the number of the tick
that saw it. The merge SHALL be in the running code when the merge commit is an ancestor of the recorded head. When the merge commit or the head is
unknown, the merge SHALL be in the running code only when the tick is a later one than the tick that saw the merge. A parent merged before this rule
existed, with neither recorded, SHALL count as loaded. For a parent in any other repository the merge SHALL be in the running code only when the tick is a later one than the tick that saw the merge.
The dependency SHALL hold
whether or not the unit's stored dependencies reach the parent. A merge dependency SHALL gate only a start or a requeue: a unit already running or in
review is neither stopped nor sent back.

#### Scenario: The parent is only in review

- **GIVEN** a planned unit with a merge dependency on a same-repo parent that is `in_review`
- **WHEN** a tick runs
- **THEN** the unit is not started, holds no place, and is reported as waiting for the parent to merge

#### Scenario: The parent merged before the tick began and is in the loaded code

- **GIVEN** a merge dependency on a kit-code parent merged earlier, whose merge commit is an ancestor of the head recorded at the start of this tick
- **WHEN** the tick runs
- **THEN** the unit is released in this tick's first round and starts when it has a place

#### Scenario: The parent merges during the tick

- **GIVEN** a tick that started with a head that does not contain the parent's merge commit, and a poll in that tick that sees the parent merged
- **WHEN** the same tick plans and starts units
- **THEN** the dependent is not started, and it is released by a later tick whose recorded head contains the merge commit

#### Scenario: Merged, but the checkout has not been fast-forwarded

- **GIVEN** a merged kit-code parent and a tick that starts without its merge commit in the checkout's head
- **WHEN** that tick runs
- **THEN** the dependent still waits, and nothing is consumed, failed or requeued

#### Scenario: The head or the merge commit is unknown

- **GIVEN** a merge dependency whose parent has no recorded merge commit, seen merged by tick 12
- **WHEN** tick 12 runs, and then tick 13
- **THEN** the dependent waits in tick 12 and is released in tick 13

#### Scenario: A parent merged before this change

- **GIVEN** a merged parent whose record has no merge commit and no tick number
- **WHEN** a tick runs
- **THEN** its merge dependency counts as met

#### Scenario: A parent in another repository

- **GIVEN** a merge dependency on a parent in another repository, merged during this tick
- **WHEN** the same tick plans units
- **THEN** the dependent waits; a later tick releases it (the tick rule, since the sha test is only for the kit's own repository)

#### Scenario: A cross-repo plain `Needs:` is read as a merge dependency

- **GIVEN** a plain `Needs: other-change group 1 — why` where that group is in another repository, and the parent in review
- **WHEN** `abk tags` runs and then a tick links the line
- **THEN** `abk tags` prints an info note that the line waits for the merge, `link_needs` stores the dependency in `merge_needs`, the dependent waits for the merge and then for the next tick, and a failed dependent's wait ends the same way

#### Scenario: The chain already implies the dependency

- **GIVEN** a merge `Needs:` whose target the unit already reaches through its dependencies, so no edge is linked
- **WHEN** the target is in review
- **THEN** the unit still waits for it to merge

#### Scenario: A unit already running

- **GIVEN** a running unit whose group gains a merge `Needs:` on a parent in review
- **WHEN** a tick runs
- **THEN** the unit is not stopped and is not sent back

### Requirement: A dependency edge is a merge edge for three reasons only

A dependency edge SHALL be `merge` when it crosses repositories, when the author wrote `merged` on the `Needs:` line, or when its dependent is a failed
unit waiting on the parent (a `failed` unit, or one a person requeued while it waited and that is parked `planned` with a gated requeue); otherwise it SHALL
be `review`. A plain `Needs:` to a group of another repository SHALL be read as a merge dependency, with an info note from `abk tags` and `abk check`, and
`link_needs` SHALL store it in `merge_needs`. An author's merge kind SHALL be binding: the planner, which returns plain `depends_on` edges only, SHALL NOT
be able to loosen it, and a replan SHALL NOT clear it for any unit, started or not. No other circumstance (the parent being in the kit's own repository,
or the dependent being an e2e-test unit) SHALL make an edge `merge`.

#### Scenario: A cross-repo plain `Needs:` is read as merge

- **GIVEN** a plain `Needs:` to a group in another repository
- **WHEN** `abk tags` runs and a tick links it
- **THEN** an info note says it waits for the merge and `merge_needs` holds the parent

#### Scenario: The planner cannot loosen an author's merge

- **GIVEN** a `Needs: parent group 1 merged — why` and a plan that lists the parent in `depends_on` like any other edge
- **WHEN** the plan is stored, the change is replanned and `link_needs` runs
- **THEN** the edge is `merge` after each, and a started unit keeps its `merge_needs`

#### Scenario: A planned dependent on a plain same-repo Needs

- **GIVEN** a planned unit with a plain same-repo `Needs:` and a parent in review
- **WHEN** a tick runs
- **THEN** it starts on the parent's branch

#### Scenario: A kit-code parent is not forced

- **GIVEN** a plain same-repo `Needs:` from another change on a parent in the kit's own repository, parent in review
- **WHEN** a tick runs
- **THEN** the dependent starts on the parent's branch; only an author's `merged` would hold it

#### Scenario: An e2e-test unit with no dev stack is not forced

- **GIVEN** an `e2e-test` unit in a repo with no `dev_stack` on a plain same-repo `Needs:`, parent in review
- **WHEN** a tick runs
- **THEN** it is not held for the merge

#### Scenario: A failed unit's wait is a merge wait, whatever the kind

- **GIVEN** a failed unit with a plain same-repo `Needs:` on a parent that is in review
- **WHEN** a tick runs
- **THEN** it stays failed with `waiting for <parent> to merge`, and it is requeued only by a tick after the merge is loaded

#### Scenario: A requeue by a person keeps the merge wait

- **GIVEN** a failed unit with a plain same-repo `Needs:` on a parent in review, which a person requeues
- **WHEN** it is parked `planned`/`gated` and a tick runs
- **THEN** it is not released while the parent is only in review

#### Scenario: A planner-chosen merge kind does not exist

- **GIVEN** a plan with an extra field naming a kind for an edge
- **WHEN** it is parsed
- **THEN** the field has no effect on the edge's kind

### Requirement: A failed unit that waits on a merge dependency resumes after the merge and the next tick

A failed unit that waits on a parent SHALL stay failed while the dependency is unmet, shown as `failed, waiting on <unit>` with the reason of
the wait. Its wait SHALL end, and it SHALL be requeued once as the wait-end rule requires, only when its dependency is met as a merge dependency is above: the parent is
merged and the requeueing tick's code contains the merge. A parent that is only in review SHALL NOT end the wait, and a merge seen by the tick that is
running SHALL defer the requeue to the next tick. The history note of the requeue SHALL say the merge was loaded and by which tick. The kind of the `Needs:` SHALL NOT matter and neither SHALL the parent's repository; a failed unit that waits on a fix change needs no `merged` line.

#### Scenario: The fix is in review

- **GIVEN** a failed unit waiting on a merge `Needs:` whose parent just entered review
- **WHEN** the tick runs
- **THEN** the unit is not requeued and still shows `failed, waiting on <parent>: waiting for <parent> to merge`

#### Scenario: The fix merges in the tick

- **GIVEN** the same unit and a tick that sees the parent merged
- **WHEN** the tick runs to the end
- **THEN** the unit is not requeued in this tick, and its line reads `waiting for the next tick to load <parent>'s merge`

#### Scenario: The next tick loads the merge

- **GIVEN** a failed unit whose merge parent merged during the previous tick, and a tick whose recorded head contains the merge
- **WHEN** it runs
- **THEN** the unit is requeued once, in the mode the wait-end rule gives, and its history says its wait ended and the merge was loaded by that tick

#### Scenario: A plain `Needs:` waits for the merge too

- **GIVEN** a failed unit waiting on a plain same-repo `Needs:` whose parent enters review
- **WHEN** the tick runs
- **THEN** it is not requeued; once the parent merges and a later tick has it, it is requeued once

#### Scenario: A requeue by a person while the merge is unmet

- **GIVEN** a failed unit with an unmet merge dependency
- **WHEN** a person runs `abk requeue` on it
- **THEN** it is parked `planned` with cause `gated` and is released only when the dependency is met

### Requirement: The status names what a merge wait is for

A wait on a dependency SHALL be worded by what is missing: `waiting for <change> group <n> to merge` while the parent is not merged;
`waiting for the next tick to load <change> group <n>'s merge` when the parent is merged, the last tick's code lacks the merge and the checkout's current
head contains it; and `waiting for the kit checkout to include <change> group <n>'s merge` when neither has it. The wording SHALL be the same in
`abk status`, the pipeline log and the graph, and `abk status` SHALL change nothing.

#### Scenario: The three texts

- **GIVEN** three planned units with a merge dependency on a parent in review, a parent merged and not in the last tick's head but in the checkout's, and a parent merged and in neither
- **WHEN** `abk status` runs
- **THEN** it prints the three wordings above, one for each

### Requirement: The graph draws a merge dependency differently

The unit graph SHALL draw a dependency in a unit's `merge_needs` as a thick edge labelled `needs, merge`, and a plain `Needs:` dependency as the thick
edge labelled `needs`, as now. The legend and `docs/unit-graph.md` SHALL say so.

#### Scenario: Two kinds of edge

- **GIVEN** a unit with one plain and one merge `Needs:` dependency
- **WHEN** the graph is generated
- **THEN** it has one `==>|needs|` edge and one `==>|needs, merge|` edge

### Requirement: Existing `merged` lines delay no unit

The first tick that reads a merge dependency SHALL print, for each dependent that is planned, failed or held and whose parent is not merged, one line
`<unit>: now waits for <parent> to merge (Needs: ... merged in tasks.md)`, and SHALL change and requeue nothing. A change whose archived tasks files hold
`merged` lines SHALL NOT be read.

#### Scenario: Every parent has merged

- **GIVEN** the `merged` lines in the planning repo's live changes when this ships, and the unit store with their parents and dependents merged
- **WHEN** a tick runs
- **THEN** no unit gains a wait and no line is printed

#### Scenario: A started dependent with a merge line and an unmerged parent

- **GIVEN** a planned unit whose group has a merge `Needs:` on a parent in review
- **WHEN** the first tick after this ships runs
- **THEN** it prints the one line and the unit waits; a running unit with the same line prints nothing
