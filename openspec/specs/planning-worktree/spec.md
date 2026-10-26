# planning-worktree Specification

## Purpose
TBD - created by archiving change planning-in-the-working-copy. Update Purpose after archive.

## Requirements

### Requirement: A planning root has one of three roles

A planning root SHALL have the role `separate` when no repo listed in `abk.yaml` is in the root's own git repository or the root is not a git repository;
`working copy` when a listed repo is in the root's repository and the root is not the pipeline worktree; and `pipeline worktree` when the root is
the path recorded in the repository's pipeline marker. The marker SHALL be a file in the repository's common git directory, written by
`abk install-timers`, shared by every worktree of the repository, and removed by `abk install-timers --remove`. Nothing in the working tree SHALL
record it. A marker whose path no longer exists SHALL NOT make any installation live.

#### Scenario: A separate planning repository

- **GIVEN** a planning root whose repos are all other repositories
- **WHEN** the role is asked
- **THEN** it is `separate`, and every command behaves as it did before this change

#### Scenario: A repo that is the planning repository, no timers installed

- **GIVEN** a root whose repository is also a listed repo's, and no marker
- **WHEN** the role is asked
- **THEN** it is `working copy`, and no installation is live

#### Scenario: The marker names the pipeline worktree

- **GIVEN** the same repository after `abk install-timers`, and a command run in the worktree it names
- **WHEN** the role is asked there
- **THEN** it is `pipeline worktree`, and run from the working copy it is `working copy` with that worktree named as the live one

#### Scenario: A marker whose path is gone

- **GIVEN** a marker naming a directory that does not exist
- **WHEN** the role and the live installation are asked
- **THEN** no installation is live, and `abk doctor` reports the marker as stale

### Requirement: The pipeline syncs its worktree to the default branch tip before every tick and track

In a `pipeline worktree`, `abk tick` and `abk track` SHALL, before anything else, fetch the default branch from `origin` (when the repository has one) and
move the worktree to its tip by fast-forwarding a detached HEAD, keeping the pipeline's own tracked-state changes. The tip SHALL be `origin/<default>`,
or the local default branch when there is no `origin`. A HEAD already at the tip SHALL be left alone, and one ahead of it (commits not yet published)
SHALL be left alone, logged, and the run SHALL go on. The sync SHALL NOT check out a branch, stash, reset or delete anything. In a `working copy` no
branch is checked out and nothing is pulled. In `separate` the previous behaviour (check out the default branch, pull with fast-forward only) SHALL
be unchanged. One routine SHALL serve the tick and the tracks, and the earlier two (`restore_default_branch` for the tick, `pull_planning` for the
tracks) SHALL be removed for an in-repo installation.

#### Scenario: New commits on the default branch

- **GIVEN** a pipeline worktree detached at an older commit with `runs/units.json` modified, and `origin/main` two commits ahead that do not touch it
- **WHEN** a tick starts
- **THEN** HEAD is at `origin/main`, `runs/units.json` is still modified with the same content, and the person's working copy has the same branch, HEAD
  and files as before

#### Scenario: Already at the tip

- **GIVEN** a pipeline worktree at `origin/main`
- **WHEN** a track starts
- **THEN** the sync reports it current and changes nothing

#### Scenario: Commits of its own, not yet published

- **GIVEN** the pipeline worktree one commit ahead of `origin/main` and not behind
- **WHEN** a tick starts
- **THEN** the sync logs that it is ahead and leaves HEAD, and the tick runs

#### Scenario: No remote

- **GIVEN** a repository with no `origin` and a local default branch with a new commit
- **WHEN** a tick starts in its pipeline worktree
- **THEN** the worktree moves to that local commit and nothing is fetched

#### Scenario: The working copy is on a feature branch with edits

- **GIVEN** a working copy on a feature branch with uncommitted edits, and a pipeline worktree for the same repository
- **WHEN** the timers' tick and track run any number of times
- **THEN** the working copy's branch, HEAD, index and every file are as they were

#### Scenario: A separate planning repository

- **GIVEN** a `separate` root left on another branch
- **WHEN** a tick starts
- **THEN** it checks the default branch out and logs the branch it found, as before

### Requirement: A sync that cannot finish stops the run with one reason and discards nothing

When the sync cannot move the worktree to the tip, the tick or track SHALL return a failure after logging one line `planning sync stopped: <reason>`, and
SHALL do nothing else in that run. It SHALL stop for: HEAD and the tip having diverged (commits on both sides); a new commit touching a tracked file the
pipeline has modified, or an untracked file in its way (git's own refusal, with its message as the reason); HEAD on a branch (the branch named, and kept);
and an unfinished merge, rebase, cherry-pick or revert. Nothing the pipeline wrote SHALL be lost in any of them.

#### Scenario: Diverged

- **GIVEN** a pipeline worktree with one commit of its own and `origin/main` with a different new commit
- **WHEN** a tick starts
- **THEN** it logs `planning sync stopped:` naming the divergence, returns failure, plans and builds nothing, and both commits and every file are intact

#### Scenario: A new commit touches a file the pipeline changed

- **GIVEN** `runs/units.json` modified in the pipeline worktree and a new commit on `origin/main` that changes it
- **WHEN** a track starts
- **THEN** it stops with git's reason, the modification is intact, and no agent is started

#### Scenario: HEAD on a stray branch

- **GIVEN** the pipeline worktree with a branch checked out
- **WHEN** a tick starts
- **THEN** it stops naming the branch and the branch still exists

#### Scenario: A merge in progress

- **GIVEN** the pipeline worktree with an unfinished rebase
- **WHEN** a tick starts
- **THEN** it stops saying so and touches nothing

### Requirement: `planning.self_pull` keeps meaning sync before running

With `planning.self_pull: false`, the tick and the tracks SHALL NOT sync, in a `pipeline worktree` or a `separate` root, and SHALL log that it is off.

#### Scenario: Off

- **GIVEN** `planning.self_pull: false` and a pipeline worktree behind `origin/main`
- **WHEN** a tick starts
- **THEN** HEAD is not moved and the log says the sync is off

### Requirement: `abk install-timers` creates the pipeline worktree and points the units at it

For a `working copy` root, `abk install-timers` SHALL create a worktree of the same repository at the default branch tip (detached, outside the
repository, `<data directory>/<repository name>/planning`), write the pipeline marker, and render the units with that worktree as `WorkingDirectory`.
It SHALL be idempotent: an existing worktree of this repository is reused and moved to the tip when it is clean, and a path that exists and is not a worktree
of this repository SHALL be refused with the path named. Run in the pipeline worktree it SHALL render the same units. For `separate` it SHALL behave
as before. `abk install-timers --remove` SHALL remove the units and the marker and leave the worktree, printing its path and how to remove it.
`--dry-run` SHALL create nothing.

#### Scenario: First install from the working copy

- **GIVEN** a working copy of an in-repo installation and no marker
- **WHEN** `abk install-timers --no-enable` runs
- **THEN** a detached worktree exists at the tip, the marker names it, each service unit's `WorkingDirectory` is that worktree, and the working copy is unchanged

#### Scenario: Run again

- **GIVEN** the install above
- **WHEN** `abk install-timers` runs again from the working copy and from the pipeline worktree
- **THEN** both report the units unchanged and no second worktree exists

#### Scenario: A directory in the way

- **GIVEN** the pipeline worktree's path holding an unrelated directory
- **WHEN** `abk install-timers` runs
- **THEN** it refuses naming the path and writes no unit

#### Scenario: Remove

- **GIVEN** an installed in-repo installation
- **WHEN** `abk install-timers --remove` runs
- **THEN** the units and the marker are gone, the worktree remains, and its path and the command that removes it are printed

#### Scenario: A separate planning repository

- **GIVEN** a `separate` root
- **WHEN** `abk install-timers` runs
- **THEN** the units point at the root and no worktree or marker is made

### Requirement: Names and machine-local files come from the repository

For a pipeline worktree the unit names and the default `planning.worktree_root` SHALL use the repository's name (the directory name of its main
working tree), not the worktree directory's. A configured `planning.worktree_root` SHALL win. The `.env` SHALL be the main working tree's when the
pipeline worktree has none, read and never written. A relative `repos.<name>.path` SHALL be relative to the planning root, and an absolute path that is a
worktree of the root's repository SHALL be taken as the root when the root is the pipeline worktree.

#### Scenario: Two installations

- **GIVEN** two repositories named differently, each with a pipeline worktree named `planning`
- **WHEN** their units are rendered
- **THEN** the unit names differ and each default worktree root is under its own repository's name

#### Scenario: A configured worktree root

- **GIVEN** `planning.worktree_root` set
- **WHEN** the root is the pipeline worktree
- **THEN** the unit worktrees are placed under the configured directory

#### Scenario: The environment file

- **GIVEN** the main working tree holds `.env` and the pipeline worktree does not
- **WHEN** the installation reads its environment file
- **THEN** it reads the main working tree's, and nothing is written there

#### Scenario: A relative repo path

- **GIVEN** `repos.<name>.path: .` and the pipeline worktree as root
- **WHEN** the repo's checkout is asked
- **THEN** it is the pipeline worktree

### Requirement: A working copy says which installation is live

`abk status` and `abk doctor` run in a `working copy` with a live pipeline worktree SHALL say that the installation is live in that worktree and print
the command to use (`abk --config <worktree>/abk.yaml <command>`, or setting `ABK_CONFIG`), and SHALL NOT present the working copy's `runs/` as
the pipeline's state. `abk tick`, `abk track`, `abk verify` and `abk archive` there SHALL refuse with the same message and a failure, unless `--config` or
`ABK_CONFIG` names a config explicitly. With no live installation they SHALL run as today.

#### Scenario: Status from the working copy

- **GIVEN** a live pipeline worktree and a command run in the working copy
- **WHEN** `abk status` runs
- **THEN** it prints the live worktree's path and the `--config` command, and the units listed are not read from the working copy's `runs/`

#### Scenario: A tick from the working copy

- **GIVEN** the same
- **WHEN** `abk tick` runs without a config named
- **THEN** it refuses with the message and runs no round

#### Scenario: A config named explicitly

- **GIVEN** the same and `--config <working copy>/abk.yaml`
- **WHEN** `abk status` runs
- **THEN** it runs as asked, naming that the config is not the live one

#### Scenario: No live installation

- **GIVEN** a working copy and no marker
- **WHEN** `abk status` runs
- **THEN** it behaves as it did before this change
