# pr-polling Specification

## Purpose
Defines that a pull request which can no longer be merged is a signal the
pipeline acts on, and how it is told apart from a host that has not answered yet.

## Requirements

### Requirement: The poll asks whether a pull request can be merged

Each poll SHALL read whether the host considers the pull request mergeable,
alongside the checks, reviews and comments it already reads, and SHALL keep that
answer in the snapshot it compares against.

#### Scenario: Mergeability is part of the snapshot

- **WHEN** an open pull request is polled
- **THEN** whether it can be merged is recorded with the rest of its state

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

### Requirement: An unanswered mergeability is not a conflict

Where the host has not determined mergeability — which it reports routinely for a
short time after any push, including the pipeline's own — the pipeline SHALL NOT
treat that as a conflict, SHALL dispatch nothing, and SHALL ask again on the next
poll.

#### Scenario: Just after the pipeline pushed

- **WHEN** a poll finds mergeability undetermined shortly after a push
- **THEN** no rework is dispatched and the answer is sought again next poll

#### Scenario: Undetermined then mergeable

- **WHEN** an undetermined answer is followed by a mergeable one
- **THEN** no rework was dispatched at any point

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

### Requirement: A review comment is recorded as seen only once a unit has taken it

The poller SHALL record a pull request's new comments as seen only when the
handler of the event they raised has taken them. A comment on a pull request
whose unit is held SHALL NOT be recorded as seen. The poller SHALL report it
again on later polls, and when the unit is released the comment SHALL be
delivered as a rework with the reviewer's words. A comment on a pull request
that no unit can ever work on, such as a satisfied unit's or one with no
recorded unit, SHALL still be consumed.

#### Scenario: A comment arrives while the unit is held

- **GIVEN** an open pull request whose unit is held
- **WHEN** a reviewer leaves an inline comment and a poll runs
- **THEN** the unit is not requeued
- **AND** the comment is not recorded as seen

#### Scenario: The unit is released

- **GIVEN** a comment left while its unit was held and not recorded as seen
- **WHEN** the unit stops being held and the next poll runs
- **THEN** the unit is requeued for rework with the reviewer's comment as its
  feedback
- **AND** the comment is recorded as seen

#### Scenario: A comment on a satisfied unit

- **GIVEN** a pull request whose unit is satisfied
- **WHEN** a reviewer comments and a poll runs
- **THEN** the comment is recorded as seen and nothing is requeued

### Requirement: A cancelled check is re-run, not reworked

The poller SHALL NOT treat a cancelled check as a failing check, and SHALL NOT
send a unit back for rework because of one. When a unit's head has cancelled
checks, the runner SHALL ask the host to run them again, without an agent, up to
a bounded number of times per head commit. When the bound is spent, the unit
SHALL stay in review with the reason recorded in its log, and SHALL NOT be
reworked. A timed-out check remains a failure. A pull request with a cancelled
check and a failing one SHALL be reworked for the failing one.

#### Scenario: The host cancels checks that never started

- **GIVEN** a unit in review whose checks on its head are all cancelled
- **WHEN** a poll finds them
- **THEN** no rework is requested
- **AND** the host is asked to run the cancelled checks again

#### Scenario: The checks keep being cancelled

- **GIVEN** a head commit whose checks were re-run up to the bound and cancelled
  again
- **WHEN** a poll finds them
- **THEN** no further re-run is asked for
- **AND** the unit's log says the host keeps cancelling the checks

#### Scenario: A check timed out

- **GIVEN** a unit whose check timed out
- **WHEN** a poll finds it
- **THEN** the unit is reworked, as for any failing check

#### Scenario: A mixed outcome

- **GIVEN** one check failed and another was cancelled
- **WHEN** a poll finds them
- **THEN** the unit is reworked for the failure and the cancelled check is
  re-run

### Requirement: Removing the hold label releases the unit it held

The poller SHALL report the `agent-hold` label leaving a pull request, and the
runner SHALL return a unit held by that label to waiting for review, without a
person requeuing it. A unit that is held for another reason (the review loop's
own hold, a stack depth cap, a toolchain the pipeline cannot build) SHALL stay
held, and the log SHALL say why. Whatever happened on the pull request during the
hold SHALL be delivered afterwards by the usual events. A release that arrives
while the unit is being built SHALL be deferred, not lost.

#### Scenario: A person removes the label

- **GIVEN** a unit held because `agent-hold` was added to its pull request
- **WHEN** the label is removed and a poll runs
- **THEN** the unit returns to waiting for review
- **AND** the pipeline's state label on the pull request is `in-review` again

#### Scenario: A hold the label did not cause

- **GIVEN** a unit the review loop held, whose pull request also had the label
  added and removed
- **WHEN** the removal is polled
- **THEN** the unit stays held and the log says the hold was not the label's

#### Scenario: A comment left during the hold

- **GIVEN** a comment added while the unit was held
- **WHEN** the unit is released
- **THEN** the next poll delivers the comment as a rework

#### Scenario: The unit is being built

- **GIVEN** a unit being built when the label is removed
- **WHEN** the poll runs
- **THEN** the release is deferred and reported again on a later poll

### Requirement: The poller records every check's status

The poller SHALL record each check's name and status in a pull request's snapshot, SHALL treat a
change from pending to failed as newly failing, and SHALL record a snapshot written before this change
afresh without sending the unit back.

#### Scenario: A check finishes failing

- **GIVEN** a snapshot with a pending check
- **WHEN** the check fails
- **THEN** the unit is sent back for rework naming the check

#### Scenario: An older snapshot

- **GIVEN** a snapshot that holds failing and cancelled names only
- **WHEN** the pull request is polled
- **THEN** the snapshot is recorded afresh and nothing is sent back

### Requirement: A change in a pull request's checks refreshes its label

When the poller records checks that change the status a unit in review reads, it SHALL bring the pull request's state label in
line with it, without waiting for the unit's stored state to change.

#### Scenario: Checks begin

- **GIVEN** a unit in review whose pull request carries the `in_review` label
- **WHEN** the poll records a pending check
- **THEN** the label becomes `checking`

#### Scenario: Checks pass

- **GIVEN** a pull request labelled `checking`
- **WHEN** the poll records every check as passed
- **THEN** the label becomes `in_review`

### Requirement: Reviews made in the web UI are a comment source

The poller SHALL read reviews made in the web UI for a unit as comments, replies and a decision on its
pull request, with identifiers that cannot collide with the host's, and SHALL write the agent's
replies back to the thread they answer.

#### Scenario: A comment from the UI

- **WHEN** a reviewer comments in the UI on a unit with a pull request
- **THEN** the next poll sees one new comment and sends the unit back for rework

#### Scenario: A reply from the agent

- **GIVEN** a rework that answers a UI comment
- **WHEN** the replies are posted
- **THEN** each appears in the thread it answers and is not seen again as a new comment

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

### Requirement: A local pull request is polled as any other

The poller SHALL treat a local forge's pull requests as it treats a host's: new comments and a
changes-requested decision send the unit back, and a merge reported by git moves it on.

#### Scenario: Request changes on a local pull request

- **WHEN** a reviewer requests changes in the UI on a local pull request
- **THEN** the unit is sent back for rework

#### Scenario: The merge

- **WHEN** git shows the branch merged
- **THEN** the unit is recorded merged and its dependents are released
