# Spec Delta

## Purpose

Defines who commits what a scheduled track writes to the planning repo, and
what keeps the planning repo on its default branch.

## ADDED Requirements

### Requirement: The runner commits a phase's bookkeeping

When a track phase ends, the runner SHALL commit the files that phase wrote in
the planning repo to the planning repo's default branch and push them, without
an agent call. The track prompts SHALL tell the agent to write those files and
not to commit, push or otherwise run git in the planning repo.

#### Scenario: A phase that writes a run log

- **WHEN** a phase's agent writes its run log and returns
- **THEN** the planning repo's default branch has one new commit containing it,
  made by the runner

#### Scenario: A push the remote rejects

- **WHEN** the push is rejected because the remote default branch has moved
- **THEN** the runner fast-forwards and pushes once more, and reports a second
  failure with the commit left in place

### Requirement: The planning repo is on its default branch after every phase

After each phase the runner SHALL confirm the planning repo is on its default
branch and that the branch still contains the commit it was at when the phase
began. If the planning repo is on another branch, the runner SHALL check the
default branch out again, keep the other branch, and report that the phase
moved it, naming the branch. If the default branch no longer contains the
earlier commit, the runner SHALL stop the run and report it, and SHALL NOT
attempt a repair.

#### Scenario: An agent creates a branch in the planning repo

- **WHEN** a phase ends with the planning repo on a branch the agent created
- **THEN** the planning repo is returned to its default branch, the phase's
  files are committed there, the created branch still exists, and the result
  names it

#### Scenario: The default branch was rewritten

- **WHEN** a phase ends and the default branch does not contain the commit it
  was at before the phase
- **THEN** the run stops, says so, and commits nothing

### Requirement: A tick starts on the default branch

Before a tick reads or writes pipeline state, it SHALL confirm the planning
repo is on its default branch, and SHALL restore it and log the branch it was
on when it is not.

#### Scenario: The planning repo was left on another branch

- **WHEN** a tick starts and the planning repo is on a branch other than its
  default
- **THEN** the tick checks out the default branch, logs the branch it found,
  and then proceeds

### Requirement: Branch-changing git in the planning repo is refused for a track's agent

For a track run, the command policy SHALL refuse a command that creates or
switches a branch, resets, force-moves a branch or cherry-picks in the planning
repo, where the command names the planning repo as its target.

#### Scenario: A branch created with the planning repo as target

- **WHEN** a track's agent runs a branch-creating git command targeting the
  planning repo
- **THEN** the command is refused with a reason saying the pipeline commits the
  planning repo's files
