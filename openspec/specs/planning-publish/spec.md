# planning-publish Specification

## Purpose
TBD - created by archiving change planning-in-the-working-copy. Update Purpose after archive.

## Requirements

### Requirement: Where abk's planning commits go is a setting

`planning.publish` SHALL be `direct` or `branch` and SHALL default to `direct`; any other value SHALL be refused when the configuration loads, naming the setting and both
values. It SHALL govern what abk itself commits in a `pipeline worktree`: a track's bookkeeping and any change a track proposes. The tick's own state and archive moves
SHALL stay uncommitted, as the tick commits nothing. In `separate` and `working copy` roles it SHALL have no effect.

#### Scenario: The default

- **GIVEN** an `abk.yaml` without `planning.publish`
- **WHEN** it is loaded
- **THEN** the value is `direct`, and `abk config --show` prints it

#### Scenario: A value that is not one of the two

- **GIVEN** `planning.publish: pr`
- **WHEN** the configuration is loaded
- **THEN** it is refused with a message naming `planning.publish` and `direct`, `branch`

### Requirement: `direct` pushes to the default branch from the pipeline worktree

With `direct`, a track's commit SHALL be made on the detached HEAD and pushed as `HEAD:refs/heads/<default>`. A rejected push SHALL fetch and rebase HEAD onto
`origin/<default>` once and push again; a second rejection SHALL be reported and the commit kept.

#### Scenario: A phase writes a run log

- **GIVEN** a pipeline worktree at the tip and `direct`
- **WHEN** a phase writes its run log and the runner settles
- **THEN** `origin`'s default branch holds a new commit with the log, and HEAD is at it

#### Scenario: A rejected push

- **GIVEN** `origin`'s default branch moved since the sync
- **WHEN** the runner pushes
- **THEN** it rebases once, pushes, and reports a second rejection with the commit kept

### Requirement: `branch` publishes a branch and a pull request and leaves the worktree syncing

With `branch`, a track's commit SHALL be pushed to `planning/<run id>-<project>-<phase>`, a pull request to the default branch SHALL be opened for it,
and HEAD SHALL be put back at the head it had before the phase so the next sync is a fast-forward. The published files SHALL stay in the worktree. When the pull
request has landed, the sync SHALL remove an untracked file or restore a modified one in its way only when its content is identical to what the incoming commits hold at that
path, and SHALL otherwise stop. The default branch SHALL NOT be pushed to.

#### Scenario: A phase writes a run log

- **GIVEN** `branch` and a pipeline worktree at the tip
- **WHEN** a phase writes its log and the runner settles
- **THEN** a `planning/...` branch holds the commit, a pull request is open for it, the default branch is unchanged, and HEAD is at its earlier commit

#### Scenario: The pull request lands

- **GIVEN** the above with the pull request landed
- **WHEN** the next tick syncs
- **THEN** it fast-forwards, the log is at the landed content, and nothing was stopped

#### Scenario: A file that differs

- **GIVEN** a published log edited locally after publishing and then landed with other content
- **WHEN** the sync runs
- **THEN** it stops with a reason and the local content is intact

### Requirement: `abk doctor` reports a protected default branch with `direct`

For an in-repo installation, `abk doctor` SHALL fail a check when `planning.publish` is `direct` and the repo's forge says the default branch is protected, naming
`planning.publish: branch`. It SHALL be an info line when the forge cannot say, and ok otherwise.

#### Scenario: Protected and direct

- **GIVEN** an in-repo installation, `direct`, and a forge reporting the default branch protected
- **WHEN** `abk doctor` runs
- **THEN** a check fails naming the setting to change

#### Scenario: Protected and branch

- **GIVEN** the same with `branch`
- **WHEN** `abk doctor` runs
- **THEN** the check is ok

#### Scenario: A forge that cannot say

- **GIVEN** a forge that cannot read the branch's protection
- **WHEN** `abk doctor` runs
- **THEN** the check is an info line saying so
