## ADDED Requirements

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
