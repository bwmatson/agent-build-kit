## MODIFIED Requirements

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

## ADDED Requirements

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
- **THEN** no rework agent is called on the conflict, and tier 1 and the review of the resolved move follow

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
