## ADDED Requirements

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

## MODIFIED Requirements

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
