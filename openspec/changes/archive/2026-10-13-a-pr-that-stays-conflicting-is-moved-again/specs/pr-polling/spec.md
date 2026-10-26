## MODIFIED Requirements

### Requirement: Becoming unmergeable sends a unit back for rework

When a pull request transitions into a state where the host reports it cannot be
merged, the pipeline SHALL send that unit back for rework, so that its branch is
rebased onto its current base and reviewed again before it is pushed. A pull
request already known to be unmergeable SHALL NOT be dispatched again on later
polls unless the requirement "A conflict that stands is a state, not a
transition" makes it a new event: a pull request already known to be
unmergeable at the same head and base tip is never dispatched twice.

#### Scenario: A branch that has gone stale behind a moving trunk

- **WHEN** a unit's branch becomes unmergeable after other work merged
- **THEN** the unit is sent back for rework, rebased and re-reviewed

#### Scenario: Still unmergeable on the next poll

- **WHEN** a unit already dispatched for a conflict is polled again and is still
  unmergeable
- **THEN** nothing further is dispatched

#### Scenario: A pull request first seen already conflicting

- **WHEN** a poll meets a pull request for the first time and the host already
  reports it cannot be merged
- **THEN** the unit is sent back for rework, as for a transition, and the
  attempt is recorded

### Requirement: The review queue shows what cannot be merged

Where the pipeline reports the pull requests awaiting review, an entry the host
says cannot be merged SHALL be marked as such, so that the queue a person works
from distinguishes what they can act on. An entry whose conflict the pipeline
has data for SHALL also say since when the host has reported it, how many times
the unit has been moved for it, and what it is waiting for.

#### Scenario: Reporting the queue

- **WHEN** the pipeline's status is printed with an unmergeable pull request
  awaiting review
- **THEN** that entry says it cannot be merged

#### Scenario: A conflict that has been moved before

- **WHEN** the status is printed for a unit in review whose pull request the
  host has reported as conflicting since 14:50 UTC and which has been moved twice
- **THEN** its line reads `conflicts with main since 14:50 UTC; moved 2 times`
  and names what it waits for

#### Scenario: A conflict nobody has moved yet

- **WHEN** the host has reported a conflict that no attempt has been made for
- **THEN** the line says `moved 0 times` and that the next poll will move it

#### Scenario: A conflict the pipeline has stopped moving

- **WHEN** the unit was held because its conflict survived its attempts or an
  attempt changed nothing
- **THEN** the line carries the hold's reason and says a person is needed

## ADDED Requirements

### Requirement: The poll records when a definite answer was read

The snapshot SHALL record the time of the poll that read the last definite
mergeability answer, and, while the answer stays `false`, the time of the first
such poll as the conflict's start. An undetermined answer SHALL keep the last
definite value and its time. A definite `true` SHALL clear the start. A snapshot
recorded before these fields exist SHALL never count as a fresh answer.

#### Scenario: Undetermined after a definite answer

- **GIVEN** a snapshot with a definite `false` read at 14:00
- **WHEN** the next poll at 14:05 finds the answer undetermined
- **THEN** the snapshot keeps `false` and the time 14:00

#### Scenario: A mergeable answer ends the conflict

- **GIVEN** a snapshot with a conflict start at 14:00
- **WHEN** a poll reads a definite `true`
- **THEN** the conflict start is cleared and the answer's time is that poll's

#### Scenario: An old snapshot

- **WHEN** the snapshot was recorded before the answer's time was kept
- **THEN** its `false` is not fresh for any unit until a poll reads a definite
  answer

### Requirement: A conflict that stands is a state, not a transition

A unit in review whose pull request the host reports as conflicting SHALL be
acted on whenever the definite answer was read after the unit's own latest push,
whether or not the recorded answer changed, and an undetermined answer after a
push, or a definite one read before it, SHALL NOT be a conflict. The unit SHALL
record the head it had pushed and the base tip when each attempt was made, and
SHALL NOT be dispatched again at the same head and the same base tip. A new
head or a new base tip SHALL be a new event. A definite `true` read after an
attempt SHALL end the episode, so that the next conflict starts counting from
zero. The stored `mergeable` SHALL NOT be the only memory of what was handled.

#### Scenario: The trunk moves after a conflict was resolved

- **GIVEN** a unit whose pull request conflicted, was reworked and pushed, and
  whose recorded answer is still `false` from the first conflict
- **WHEN** the trunk merges more work and a poll reads a definite `false` after
  the unit's push
- **THEN** a new attempt is dispatched for the new base tip

#### Scenario: The same conflict at the same head and base tip

- **GIVEN** an attempt recorded at a head and a base tip
- **WHEN** later polls read `false` at the same head and base tip
- **THEN** nothing is dispatched

#### Scenario: Undetermined after the unit's own push

- **GIVEN** a unit that has just pushed and a recorded answer of `false`
- **WHEN** a poll finds the answer undetermined
- **THEN** no attempt is dispatched

#### Scenario: A definite answer read before the push

- **GIVEN** a definite `false` read at 14:20 and a unit that pushed at 14:31
- **WHEN** the next poll still reports it undetermined
- **THEN** the old answer is not fresh and nothing is dispatched

#### Scenario: A new head at the same base tip

- **GIVEN** an attempt that pushed a new head and a definite `false` read after
  that push at the same base tip
- **WHEN** the poll runs
- **THEN** the next attempt is dispatched, counted at that base tip

#### Scenario: The conflict is gone

- **WHEN** a poll reads a definite `true` after an attempt
- **THEN** the count and the recorded tip are cleared and a later conflict
  starts at attempt one

#### Scenario: A unit that is not in review

- **WHEN** the host reports a conflict for a unit that is running, planned,
  held, failed or satisfied
- **THEN** nothing is dispatched and the answer is recorded as it is

### Requirement: A conflict that cannot be resolved ends in a hold with a reason

Attempts at one base tip SHALL be bounded by `limits.max_review_rounds`. A unit
whose conflict survives that many attempts SHALL be held with the review loop
as the cause and a note naming the base and the count. An attempt that left the
head unchanged while the host, read after it, still reports a conflict SHALL
hold the unit at once, since nothing the next attempt could use has changed. A
rework that changes nothing SHALL NOT count as resolving a conflict: only a
definite `true` from the host ends it. A new base tip SHALL start the count at
zero, so a trunk that keeps moving is followed, one attempt per move.

#### Scenario: The attempts run out

- **GIVEN** `max_review_rounds` is 3 and three attempts at one base tip each
  pushed a new head
- **WHEN** a poll reads a definite `false` after the third push
- **THEN** the unit is held, and the note names the base and says it was moved
  3 times without the host accepting it

#### Scenario: An attempt that changed nothing

- **GIVEN** a conflict rework whose agent found nothing to change and left the
  head as it was
- **WHEN** a poll reads a definite `false` after the run
- **THEN** the unit is held at once with the reason that the last attempt
  changed nothing, and no further attempt is dispatched

#### Scenario: The recorded answer is not the proof

- **GIVEN** a unit reworked once whose recorded answer is `false` since before
  the rework
- **WHEN** the rework ends with the head unchanged
- **THEN** the conflict is not counted as resolved

#### Scenario: A trunk that keeps moving

- **WHEN** each of three trunk merges is followed by a conflict that one
  attempt resolves
- **THEN** each is attempted once, the count starts at zero at each base tip,
  and no hold results
