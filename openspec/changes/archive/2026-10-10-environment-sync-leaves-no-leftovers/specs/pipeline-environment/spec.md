## ADDED Requirements

### Requirement: Lock files written by the environment's sync are not leftovers

A path named in a repository's `environment.inputs.lock` SHALL be pipeline-owned in that repository's unit
worktrees. The check for uncommitted work SHALL NOT hold a unit for such a path, whether it is untracked or
modified, SHALL NOT discard it, and SHALL NOT list it as a leftover to an agent. The paths SHALL be taken from
the configured inputs and never from a name in the framework. Every other uncommitted path SHALL hold the unit
as before.

#### Scenario: An untracked lock created by the sync

- **GIVEN** a repository with an environment whose `sync` creates an untracked lock file named in its lock inputs
- **WHEN** the next step of the unit asks for the worktree
- **THEN** the unit is not held, and the lock file is still in the worktree

#### Scenario: A tracked lock rewritten by the sync

- **GIVEN** a lock file the branch tracks, rewritten by the `sync`
- **WHEN** the next step asks for the worktree
- **THEN** the unit is not held and the rewrite is not discarded

#### Scenario: A human's other uncommitted file

- **GIVEN** a worktree with an uncommitted file that is not named in the lock inputs, and a rewritten lock
- **WHEN** the next step asks for the worktree
- **THEN** the unit is held with the cause `dirty_worktree`, and the paths named are only the other file

#### Scenario: The lock is matched by configuration

- **GIVEN** two repositories whose lock inputs name different files
- **WHEN** each unit's worktree holds both files uncommitted
- **THEN** in each repository only the file its own configuration names is ignored, and the framework holds no list of lock file names

#### Scenario: A repository without an environment section

- **WHEN** a repository has no `environment` section
- **THEN** an uncommitted lock file holds the unit as any other uncommitted file does

### Requirement: The commit step carries a lock the unit changed and never one it did not

When the pipeline commits a unit's work, a tracked lock file named in the lock inputs SHALL be committed with
the change when the unit changed a dependency input against the point its branch left the base, and SHALL
otherwise be restored to the branch's version. A lock file the branch does not track SHALL NOT be committed.

#### Scenario: A lock the unit changed and committed is kept

- **GIVEN** a unit that changed a dependency manifest, whose `sync` rewrote the tracked lock
- **WHEN** the pipeline commits the unit's work
- **THEN** the manifest and the lock are in the same commit

#### Scenario: A lock rewritten with no dependency change

- **GIVEN** a tracked lock rewritten by the `sync` while the unit changed no dependency input
- **WHEN** the pipeline commits the unit's work
- **THEN** the lock is not in the commit and the worktree has no uncommitted change to it

#### Scenario: An untracked lock is not committed

- **GIVEN** a repository that does not track its lock, whose `sync` created one
- **WHEN** the pipeline commits the unit's work
- **THEN** the lock is not in the commit and remains in the worktree

#### Scenario: A restack with a rewritten lock

- **GIVEN** a unit whose tracked lock the unit did not change and the `sync` rewrote
- **WHEN** the branch is moved onto a new base
- **THEN** the move succeeds and the unit is not held
