# track-bookkeeping Specification

## Purpose
Defines who commits what a scheduled track writes to the planning repo, and
what keeps the planning repo on its default branch.

## Requirements

### Requirement: The runner commits a phase's bookkeeping

When a track phase ends, the runner SHALL commit the files that phase wrote in
the planning repo to the planning repo's default branch and push them, without
an agent call. In a pipeline worktree (a worktree of the repository held at the
default branch tip) the commit is made on the detached HEAD and pushed as
`HEAD:<default branch>`, or published as a branch and pull request when
`planning.publish` is `branch`. The track prompts SHALL tell the agent to write those files and
not to commit, push or otherwise run git in the planning repo.

#### Scenario: A phase that writes a run log

- **WHEN** a phase's agent writes its run log and returns
- **THEN** the planning repo's default branch has one new commit containing it,
  made by the runner

#### Scenario: A push the remote rejects

- **WHEN** the push is rejected because the remote default branch has moved
- **THEN** the runner fast-forwards and pushes once more, and reports a second
  failure with the commit left in place

#### Scenario: A pipeline worktree

- **GIVEN** a planning root that is a pipeline worktree detached at the tip
- **WHEN** a phase's agent writes its run log and returns
- **THEN** the runner commits it on the detached HEAD and pushes it to the default branch, with no branch checked out

### Requirement: The planning repo is on its default branch after every phase

After each phase the runner SHALL confirm the planning repo is on its default
branch and that the branch still contains the commit it was at when the phase
began. If the planning repo is on another branch, the runner SHALL check the
default branch out again, keep the other branch, and report that the phase
moved it, naming the branch. If the default branch no longer contains the
earlier commit, the runner SHALL stop the run and report it, and SHALL NOT
attempt a repair. In a pipeline worktree, which has no branch checked out, the
runner SHALL instead confirm that HEAD still contains the commit it was at when
the phase began, put HEAD back there detached when the agent left it on a branch
(keeping the branch and naming it), and stop the run, repairing nothing, when it
does not.

#### Scenario: An agent creates a branch in the planning repo

- **WHEN** a phase ends with the planning repo on a branch the agent created
- **THEN** the planning repo is returned to its default branch, the phase's
  files are committed there, the created branch still exists, and the result
  names it

#### Scenario: The default branch was rewritten

- **WHEN** a phase ends and the default branch does not contain the commit it
  was at before the phase
- **THEN** the run stops, says so, and commits nothing

#### Scenario: A branch left in a pipeline worktree

- **GIVEN** a pipeline worktree and a phase that ends with HEAD on a branch the agent created
- **WHEN** the runner settles
- **THEN** HEAD is detached at the earlier commit, the branch still exists and is named, and the phase's files are committed from there

#### Scenario: HEAD rewritten in a pipeline worktree

- **GIVEN** a pipeline worktree and a phase after which HEAD does not contain the earlier commit
- **WHEN** the runner settles
- **THEN** the run stops, says so, and commits nothing

### Requirement: A tick starts on the default branch

Before a tick reads or writes pipeline state, it SHALL confirm the planning
repo is on its default branch, and SHALL restore it and log the branch it was
on when it is not. In a pipeline worktree it SHALL instead sync the worktree to
the default branch tip as the tracks do, and SHALL stop with one logged reason
when it cannot.

#### Scenario: The planning repo was left on another branch

- **WHEN** a tick starts and the planning repo is on a branch other than its
  default
- **THEN** the tick checks out the default branch, logs the branch it found,
  and then proceeds

#### Scenario: A pipeline worktree behind the tip

- **GIVEN** a pipeline worktree behind `origin`'s default branch
- **WHEN** a tick starts
- **THEN** it fast-forwards the detached HEAD to the tip and proceeds, without checking a branch out

#### Scenario: A pipeline worktree that cannot be synced

- **GIVEN** a pipeline worktree that has diverged from the tip
- **WHEN** a tick starts
- **THEN** it logs one reason, returns a failure and reads or writes no state

### Requirement: Branch-changing git in the planning repo is refused for a track's agent

For a track run, the command policy SHALL refuse a command that creates or
switches a branch, resets, force-moves a branch or cherry-picks in the planning
repo, where the command names the planning repo as its target.

#### Scenario: A branch created with the planning repo as target

- **WHEN** a track's agent runs a branch-creating git command targeting the
  planning repo
- **THEN** the command is refused with a reason saying the pipeline commits the
  planning repo's files
