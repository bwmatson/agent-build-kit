## ADDED Requirements

### Requirement: A restack in the lane honours the usage guard for its agent step

A restack that runs in the lane SHALL ask the usage guard before each call of the conflict step's agent, by the same decision, with the same
thresholds and the same estimate when a read is refused, that a unit's agent step or a unit start asks. A clean move runs no agent and spends
no usage, and SHALL NOT be asked of the guard. When the guard refuses, the rebase SHALL be aborted inside the repository's turn, the branch
SHALL be left where it was, the unit SHALL be left planned with a deferred restack, and the restack SHALL be tried again when the pause
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
