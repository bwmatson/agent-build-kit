## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Unchanged elsewhere

This SHALL apply only to conflicts during a restack. The step that ports a unit onto a
predecessor it could not be replayed onto SHALL do what it did before (keep the old work, reset the
branch, decide for each uncertain test, check the accounting), SHALL be reached only when the first two
steps of the conflict step cannot settle the conflict, and SHALL be unaffected otherwise, as SHALL every other step.

#### Scenario: A unit that has to be ported

- **WHEN** a unit cannot be replayed and is ported instead
- **THEN** nothing about that step changes
