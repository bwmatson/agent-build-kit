## ADDED Requirements

### Requirement: A toolchain profile may name the files its commands create

The toolchain profile SHALL offer an optional hook that, given a repository root, returns the paths or patterns,
relative to the repository, of the files the profile's own commands create or rewrite in a worktree. A profile
that has none SHALL return an empty list, and a profile without the hook SHALL count as returning one. A path
that is absolute, leaves the repository or names the version-control directory SHALL be ignored. Framework code
SHALL take these paths from the profile and SHALL NOT name any of them.

#### Scenario: A profile names a file

- **GIVEN** a profile that returns a lock file as a file its commands create
- **WHEN** the owned paths of a repository using that profile are resolved
- **THEN** the file is among them

#### Scenario: A profile with nothing

- **GIVEN** a profile that returns an empty list, or has no such hook
- **WHEN** the owned paths of a repository using it are resolved
- **THEN** it adds none

#### Scenario: A second ecosystem

- **GIVEN** a profile in a test that returns a different, nested file
- **WHEN** a unit runs that profile's commands in a repository with no environment section
- **THEN** that file is owned exactly as the first profile's is, and the first profile's file is not

#### Scenario: An unusable path

- **WHEN** a profile returns a path that is absolute, contains `..` or names the version-control directory
- **THEN** it is ignored

### Requirement: Files a profile's commands create are pipeline-owned

A path a repository's profile names SHALL be pipeline-owned in that repository's worktrees, with a repository
that declares no `environment` section included. An untracked or modified one SHALL NOT hold a unit, SHALL NOT
be listed to an agent as a leftover and SHALL NOT be discarded by the pipeline, and an untracked one SHALL NOT
be committed. A tracked one SHALL follow the rule for the environment's lock files when the repository's
environment declares dependency inputs, and SHALL otherwise be ordinary tracked work. The owned set SHALL merge
the profile's paths with `environment.inputs.lock` and `environment.artifacts`; a path named by several of them
SHALL be one entry, an artifact taking precedence over a lock and a lock over a profile path. A repository with
projects SHALL own each project's profile paths under the project's path. A repository whose profile is unknown
SHALL get the environment's lists only, without an error from the check.

#### Scenario: A repository with no environment section

- **GIVEN** a repository with no environment section whose tier 1 commands create a file its profile names
- **WHEN** the next step of the unit asks for the worktree
- **THEN** the unit is not held and the file is still there

#### Scenario: The untracked file is not committed

- **GIVEN** an untracked file its profile names, beside the unit's own changes
- **WHEN** the pipeline commits the unit's work
- **THEN** the file is not in the commit and is still in the worktree

#### Scenario: A person's file still holds

- **GIVEN** such a file and an unrelated uncommitted file
- **WHEN** the next step asks for the worktree
- **THEN** the unit is held with the cause `dirty_worktree`, naming only the unrelated file

#### Scenario: A repository that tracks the file

- **GIVEN** a repository that tracks a file its profile names and whose environment declares dependency inputs
- **WHEN** the unit changed a dependency input and the file was rewritten
- **THEN** the file is committed with the change; and when no dependency input changed it is restored and not
  committed

#### Scenario: A tracked file with no dependency inputs to compare

- **GIVEN** a repository with no environment section that tracks a file its profile names
- **WHEN** the file is modified
- **THEN** it is ordinary work, held for and committed as before

#### Scenario: A profile with nothing changes nothing

- **GIVEN** a repository whose profile names no files and which has no environment section
- **WHEN** the worktree is checked and the work committed
- **THEN** both behave as before

#### Scenario: The same path named twice

- **GIVEN** a path named by the profile and by `environment.inputs.lock`
- **WHEN** the unit is committed
- **THEN** it is handled once, as a lock

#### Scenario: A path an artifact pattern also names

- **GIVEN** a path named by the profile and matched by `environment.artifacts`
- **WHEN** the unit is committed
- **THEN** it is handled as an artifact and is never staged

#### Scenario: An unknown profile

- **GIVEN** a repository naming a profile that is not registered
- **WHEN** the owned set is resolved
- **THEN** it holds the environment's lists only and the check does not raise
