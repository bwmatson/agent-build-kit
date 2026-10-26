# restack-conflicts Specification

## Purpose
Defines that a conflict the pipeline has already resolved is replayed rather than re-derived,
and that a replayed resolution is confirmed before it is used.

## Requirements

### Requirement: A conflict resolved once is replayed when it recurs

The pipeline SHALL record how a restack's conflicts were resolved and SHALL replay a recorded
resolution when the same conflict appears again, for every unit of the repository — relying on
the cache git keeps in the repository's common directory rather than copying anything between
worktrees.

#### Scenario: The same hunk in a later unit

- **WHEN** a restack of one unit hits a conflict already resolved while restacking another unit
  of the same repository
- **THEN** the recorded resolution is applied to the file, rather than the conflict being
  derived again

#### Scenario: A conflict never seen before

- **WHEN** a conflict has no recorded resolution
- **THEN** it is resolved as it is today

### Requirement: A replayed resolution is left for confirmation, not staged

A replayed resolution SHALL be written into the working tree but SHALL NOT be staged, and its
path SHALL remain unmerged, so that no recorded resolution reaches a commit without something
looking at it. The resolver SHALL be told which paths carry a replayed resolution, and SHALL
stage it, correct it, or say that it was wrong.

#### Scenario: The resolution is right

- **WHEN** the resolver examines a replayed resolution and agrees with it
- **THEN** it stages it and the rebase continues

#### Scenario: The resolution is wrong

- **WHEN** the resolver judges a replayed resolution incorrect
- **THEN** it resolves the path itself, and that resolution is what is recorded

#### Scenario: Nothing passes unexamined

- **WHEN** a restack completes with replayed resolutions among its conflicts
- **THEN** each of them was staged deliberately rather than automatically

### Requirement: The operator's checkout is not reconfigured

The pipeline SHALL apply this to its own git invocations rather than by writing the setting into
the repository's stored configuration, so that an operator working in the same checkout is
unaffected unless they enable it themselves.

#### Scenario: A human in the same checkout

- **WHEN** an operator rebases in the repository the pipeline builds in
- **THEN** their git behaves as they configured it, not as the pipeline configured it

### Requirement: Unchanged elsewhere

This SHALL apply only to conflicts during a restack. The step that ports a unit onto a
predecessor it could not be replayed onto SHALL do what it did before (keep the old work, reset the
branch, decide for each uncertain test, check the accounting), SHALL be reached only when the first two
steps of the conflict step cannot settle the conflict, and SHALL be unaffected otherwise, as SHALL every other step.

#### Scenario: A unit that has to be ported

- **WHEN** a unit cannot be replayed and is ported instead
- **THEN** nothing about that step changes

### Requirement: A conflict is resolved in one session, smallest change first

A restack conflict SHALL be settled by one agent session, started in the run that finds it, whose first prompt states an order: first
change only the conflicting hunks and only the files that conflict; if the pipeline's checks then fail, widen to the unit's other files
that depend on the conflict; only when that cannot work, port the unit's old work onto the new base. Each step of the order SHALL be a
call of the same session, and the pipeline SHALL check each before going on. The checks SHALL be that no conflict marker is left in a
conflicted file, that the unit's own distinctive tokens are still present, and that none of the unit's own tests is missing. A failed
check SHALL be named to the agent in the next call. When an agent leaves a conflict marker in place to say it cannot settle the conflict,
that SHALL count as a failed check, not as an error. No separate resolver run and adapt run SHALL be started for one conflict, and a
conflict settled by one of the first two steps SHALL NOT start the port.

#### Scenario: A hunk conflict is fixed in the conflicting files

- **GIVEN** a restack that conflicts in two files
- **WHEN** the agent changes only those files and the checks pass
- **THEN** the rebase continues, the move is recorded as resolved in those files, and no port is started

#### Scenario: A fix that breaks the unit's own tokens

- **GIVEN** a first call whose result leaves one of the unit's own tokens missing from the conflicted files
- **WHEN** the check runs
- **THEN** the agent is told which token is missing and asked again in the same session, with leave to change the unit's other files that depend on the conflict

#### Scenario: A fix that drops one of the unit's own tests

- **GIVEN** a first call whose result removes a test the unit added
- **WHEN** the check runs
- **THEN** the agent is asked again in the same session, naming the test

#### Scenario: A conflict that needs a port

- **GIVEN** a conflict the widened step cannot settle, or an agent that leaves the markers in place
- **WHEN** the checks fail a second time
- **THEN** the unit's old work is kept under a reference, the branch is reset onto the new base, and the port is asked for in the same session

#### Scenario: Files beyond the conflict are named

- **WHEN** a resolution changed a file that did not conflict
- **THEN** that file is named with the conflicted ones among the files the move resolved, so the review is told

#### Scenario: The session cannot be continued

- **GIVEN** a recorded session the runtime cannot continue, or a workspace with reuse off
- **WHEN** a later call of the step runs
- **THEN** it runs in a new session whose prompt repeats the order and names the check that failed

#### Scenario: A rate limit during the step

- **WHEN** the agent refuses a call of the step because a usage window is spent
- **THEN** the rebase is aborted, the branch is where it was, the unit is not marked as having a conflict nobody could settle, and the move is retried when the window opens

### Requirement: A replayed resolution is staged deliberately in the one session

Within the one session, a replayed resolution SHALL still be written into the working tree unstaged and its path SHALL stay unmerged until
the step stages it. The first prompt SHALL say which paths carry one. An agent that leaves a replayed path unchanged accepts it, one that
edits it replaces what is cached, and one that leaves a conflict marker in it rejects it: the cached entry SHALL then be forgotten before
anything else is done, so the next unit to meet the conflict sees the conflict itself, and the step SHALL count as having failed its check
and go on to the next step of the order rather than abort the move for a person.

#### Scenario: A replayed resolution is accepted

- **GIVEN** a conflict that arrives with a replayed resolution
- **WHEN** the agent leaves it unchanged and the checks pass
- **THEN** the pipeline stages it and the rebase continues, and the path was staged by that act, not by git

#### Scenario: A replayed resolution is corrected

- **WHEN** the agent edits a replayed path
- **THEN** its edit is what is cached for the next unit

#### Scenario: A replayed resolution is rejected

- **WHEN** the agent leaves a conflict marker in a replayed path
- **THEN** the cached entry is forgotten, and the step goes on to its next call or to the port instead of aborting the move

#### Scenario: Nothing passes unexamined

- **WHEN** a restack with replayed resolutions among its conflicts completes
- **THEN** each of them was staged by the step after its checks

### Requirement: The conflict step runs under the usage gate in the run that finds the conflict

The agent step SHALL run in the unit's run, after the run's usage gate, at the start of a resume and again when the check before a push
finds a conflict, and SHALL NOT run inside the check before a push. A usage pause SHALL defer only the agent step: a move that applies
cleanly in the same pause SHALL proceed. A conflict found by the check before a push SHALL be settled by the step once in the run; a
second time in the same run the unit SHALL be left planned to be moved on a later tick, so a base that keeps moving cannot loop. A conflict
the step settled SHALL NOT count as that second time.

#### Scenario: A conflict found before a push

- **WHEN** the check before a push meets a conflict
- **THEN** nothing is pushed, the run goes back to its restack, and the step settles the conflict in that run

#### Scenario: A base that keeps moving

- **GIVEN** a run that has already gone back to its restack once
- **WHEN** the check before the next push finds the base moved again
- **THEN** the unit is left planned for a later tick

#### Scenario: A usage pause and a clean move

- **GIVEN** a usage pause and two units to move, one conflicting and one applying cleanly
- **WHEN** both are restacked
- **THEN** the clean one is moved, and the conflicting one waits for the pause to end

### Requirement: Each call of the conflict step is recorded as the restack node

Every agent call of the step SHALL write one ledger row under the node `restack`, naming the unit being moved, the repository and the
change, whether the call ran in a stack move or in a run, and in a run SHALL be a call of the unit's build session.

#### Scenario: Two calls of one conflict

- **WHEN** the step asks the agent a second time after a failed check
- **THEN** the ledger holds two `restack` rows for the unit

#### Scenario: A stack move

- **WHEN** a merge's stack move resolves a child's conflict
- **THEN** its calls are recorded as `restack` for that child

### Requirement: A restack in the lane honours the usage guard for its agent step

A restack that runs in the lane, whether only the move or the whole moved-base run, SHALL ask the usage guard before each call of any
agent it makes (the conflict step's resolver, the port, a rework, a review), by the same decision, with the same
thresholds and the same estimate when a read is refused, that a unit's agent step or a unit start asks. A clean move runs no agent and spends
no usage, and SHALL NOT be asked of the guard. The resolver that a run's own move asks SHALL be asked of the guard as the lane's stack
move's is, and not left to the runtime's refusal. When the guard refuses, the rebase SHALL be aborted inside the repository's turn, the branch
SHALL be left where it was, the unit SHALL be left planned with a deferred restack (a run past its move SHALL be interrupted at the step, the unit staying with its
thread there, and resumed by the lane), and the restack SHALL be tried again when the pause
ends or at the next scan, and SHALL NOT be tried on a recurring timer of its own. An admission on an estimate SHALL be attributed to the unit
being moved.

#### Scenario: A conflicting restack under a usage pause

- **GIVEN** a usage pause and two units to move, one that conflicts and one that applies cleanly
- **WHEN** both are restacked
- **THEN** the clean one is moved at once, and the conflicting one is aborted, left planned with a deferred restack, and moved when the pause ends

#### Scenario: A refused read with headroom

- **GIVEN** a restack whose conflict needs the agent while the usage read is refused and the estimate leaves room
- **WHEN** the guard is asked
- **THEN** it answers as it does for a unit start, and the agent runs on the estimate's say

#### Scenario: The pause ends

- **GIVEN** a unit left with a deferred restack by a usage pause
- **WHEN** the pause ends
- **THEN** the next scan moves it, asking the guard again

#### Scenario: A clean move needs no decision

- **WHEN** a restack applies cleanly during a pause
- **THEN** the guard is not asked

#### Scenario: A rate limit during the agent call

- **GIVEN** a restack whose agent call is refused by the runtime
- **WHEN** the refusal is raised
- **THEN** the rebase is aborted and the unit left planned with a deferred restack, as before

#### Scenario: The port under a pause

- **GIVEN** a moved-base run that reaches the port while a usage pause stands
- **WHEN** the guard refuses
- **THEN** the run is interrupted at the port, the unit stays with its thread there, and the lane resumes it when the pause ends, asking the guard again

#### Scenario: A review in the lane

- **GIVEN** a moved-base run that reaches the review of the result
- **WHEN** the guard is asked
- **THEN** it is asked by the decision a review in a build worker asks, and the review uses the review model and writes its usual ledger rows

#### Scenario: The resolver of a run's own move

- **GIVEN** a moved-base run whose move meets a conflict while the guard refuses
- **WHEN** the resolver would be called
- **THEN** it is not called, the rebase is aborted, and the run is deferred until the pause ends

#### Scenario: A refusal is not an attempt

- **WHEN** a run is deferred by the guard before its first agent call
- **THEN** no attempt is counted for it

### Requirement: A moved base found twice in one run still holds the unit, and the lane then moves it

The hold a run makes for a second moved base SHALL be unchanged: the first time a run finds its base moved before a push it goes back to the
conflict step in the same run, and the second time it holds the unit planned with the moved base as the cause. The unit so held SHALL be owed
a restack, and the lane SHALL move it at once instead of leaving the move for a build slot. A conflict that the step settled in the run SHALL
NOT count as the second.

#### Scenario: The second hold

- **GIVEN** a run that found its base moved twice before its push
- **WHEN** the run ends
- **THEN** the unit is planned with the moved base as its cause, and its move starts at once in the lane

#### Scenario: One hold

- **GIVEN** a run that found its base moved once and settled the conflict in the same run
- **WHEN** it reaches its push
- **THEN** it is not held, and the lane is not asked

### Requirement: A restack is recorded as the restack node

Every agent call the lane makes SHALL be recorded as a call of node `restack` with the unit being moved, its change and its repository, and
a clean move SHALL write no ledger row.

#### Scenario: A resolver call in the lane

- **WHEN** the lane's conflict step asks the agent
- **THEN** a `restack` row is written for the unit, with its change and repository

#### Scenario: A clean move in the lane

- **WHEN** the lane moves a unit with no conflict
- **THEN** no agent row is written

### Requirement: A conflict that stands on the trunk is moved by the restack first

Where a unit in review is based on the trunk and the host reports its pull
request as conflicting, the first attempt SHALL be the stack move: the branch
SHALL be replayed onto the trunk's tip with the conflict resolver scoped to
the files that conflict and recorded resolutions replayed, as for a unit whose
parent merged. The attempt SHALL follow the stack move's outcomes: a clean move
of an approved head with an unchanged diff SHALL be pushed and the unit SHALL
stay in review; a move that needed the resolver or changed the diff SHALL leave
the unit planned for review before anything is pushed. A conflict the stack move
cannot settle, a second attempt at the same base tip, a unit that is not based
on the trunk and a unit whose thread cannot take the event SHALL go to the
conflict rework. The attempt SHALL run only while the unit's branch is free,
SHALL leave the event for the next poll when it is held, and SHALL ask the usage
guard before the resolver as any resolver call does, so that under a usage
pause a clean move proceeds and one that needs the resolver waits.

#### Scenario: A clean move

- **GIVEN** a trunk-based unit in review with an approved head and a conflict
  the trunk's new commits made
- **WHEN** the stack move replays its commits cleanly
- **THEN** the branch is pushed with the lease, a comment says it was restacked,
  and the unit stays in review with no agent run

#### Scenario: A move that needed the resolver

- **WHEN** the replay conflicts and the scoped resolver settles it
- **THEN** nothing is pushed, and the unit is planned for review of the resolved
  move

#### Scenario: A conflict the move cannot settle

- **WHEN** the stack move leaves a conflict it cannot settle
- **THEN** the unit is sent back through the conflict rework, and the attempt is
  counted once

#### Scenario: The second attempt at the same base tip

- **GIVEN** a stack move that pushed a head at a base tip
- **WHEN** the host still reports a conflict after that push at the same tip
- **THEN** the next attempt is the conflict rework

#### Scenario: A branch that is being built

- **WHEN** the unit's branch is held by a run
- **THEN** nothing is moved, no attempt is recorded and the event comes again
  next poll

#### Scenario: Under a usage pause

- **GIVEN** a usage pause in force
- **WHEN** a conflicting unit is dispatched and its move is clean
- **THEN** it is moved and pushed, and when it needs the resolver it is left
  for the poll after the pause, with no attempt counted

### Requirement: A conflict rework starts with the move

A unit that is sent back for a conflict and whose run is a moved-base run SHALL start that run at the move, whether its thread is parked
or not: the branch SHALL be moved onto its base, with the resolver and the port as the move needs, before any rework agent is asked about
the conflict. When the move settles the conflict, clean or resolved, the feedback that names the conflict SHALL be cleared and no
rework agent SHALL be called on it. When the move leaves a conflict the resolver could not settle, the port SHALL run, and the rework
SHALL then run with the conflict's feedback only for what the port left. A unit that has rework input of its own SHALL be sent back as
it is today.

#### Scenario: A parked thread, a clean move

- **GIVEN** a unit in review with a parked thread whose pull request has become conflicting, and a base that moves onto the branch cleanly
- **WHEN** the conflict is sent back
- **THEN** the run starts at the move, the branch holds the base, the conflict feedback is cleared, and no rework agent is called

#### Scenario: The resolver settles it

- **WHEN** the move needs the resolver and the resolver settles the conflict
- **THEN** no rework agent is called on the conflict, and unit-test and the review of the resolved move follow

#### Scenario: The resolver cannot settle it

- **WHEN** the move leaves a conflict the resolver cannot settle
- **THEN** the port runs, and the rework runs with the conflict's feedback only for what the port left

#### Scenario: A unit with no thread

- **GIVEN** a unit sent back for a conflict that has no thread
- **WHEN** its run starts
- **THEN** it starts at the move as before

#### Scenario: A unit with feedback to answer

- **GIVEN** a unit with unanswered review feedback that is sent back for a conflict
- **WHEN** the event is delivered
- **THEN** it is delivered as a rework as it is today, and the run is a build

### Requirement: A moved-base run that cannot settle its conflict is bounded and ends in a hold

Each moved-base run the lane starts for a unit SHALL be one attempt at the tip of the unit's base, recorded with the unit's pushed head and
the time, and SHALL be counted with the attempts the conflict handler makes at the same tip. Attempts at one tip SHALL be bounded by
`max_review_rounds`. A unit whose attempts at the tip are spent SHALL NOT be handed to the lane again; it SHALL be held, with the
review loop as the cause, and a note naming the base, the tip, the number of attempts and how the last ended, and SHALL be run again only
after a person releases it. A new tip SHALL start the count at zero. A run resumed after an interruption SHALL be the same attempt, and a
run that never got going (its branch held, a usage pause before its first agent call) SHALL NOT count. A run SHALL NOT be continued
in the lane because an earlier one failed to settle the conflict, other than by the next attempt.

#### Scenario: The attempts run out

- **GIVEN** `max_review_rounds` is 3 and three runs at one base tip each ended with the conflict standing
- **WHEN** the unit is next found
- **THEN** it is held with the review loop as the cause and a note naming the base, the tip and three attempts, and the lane does not start a fourth

#### Scenario: A trunk that keeps moving

- **WHEN** each of three moves of the base is followed by a run that settles it
- **THEN** each is attempted once, the count starts at zero at each tip, and no hold results

#### Scenario: Shared with the conflict handler

- **GIVEN** one attempt the conflict handler made at a tip
- **WHEN** the lane runs the unit at the same tip
- **THEN** the lane's run is the second attempt at that tip, not the first

#### Scenario: An interrupted run is one attempt

- **GIVEN** a run interrupted by a usage pause after its port
- **WHEN** the lane resumes it
- **THEN** the attempts counted are as they were

#### Scenario: A run that did not start

- **GIVEN** a unit whose branch was held when the lane took it
- **WHEN** the lane leaves it owed
- **THEN** no attempt is counted

#### Scenario: A held unit is not found again

- **GIVEN** a unit held for spent attempts
- **WHEN** a scan runs
- **THEN** it is not handed to the lane, and it is run again only after a person releases it
