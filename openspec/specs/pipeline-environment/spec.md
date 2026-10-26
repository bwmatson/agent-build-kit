# pipeline-environment Specification

## Purpose
TBD - created by archiving change environment-sync-leaves-no-leftovers. Update Purpose after archive.

## Requirements

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

### Requirement: Framework code names no ecosystem outside profiles and init

Framework source other than the toolchain profiles and the init detectors they provide SHALL NOT name a package
manager, a dependency manifest or a lock file from a configured list, and the repository SHALL carry a check that
fails when it does. Files that name one today SHALL be on an allowlist that only shrinks, and a file on it whose
names are gone SHALL fail until removed. The framework's own tooling SHALL be a separate, fixed list with a
reason for each entry. Behaviour that depends on an ecosystem SHALL be specified as configured argv lists, path
patterns and profile hooks, and its tests SHALL include a second ecosystem's shape beside the first.

#### Scenario: A package manager named in framework source

- **GIVEN** a source file outside the profiles and init that names a listed package manager or lock file and is
  on neither list
- **WHEN** the check runs
- **THEN** it fails naming the file and line

#### Scenario: An allowlisted file that no longer offends

- **GIVEN** a file on the allowlist whose matches have been removed
- **WHEN** the check runs
- **THEN** it fails naming the stale entry

#### Scenario: A name inside a profile

- **WHEN** a profile or an init detector names a package manager
- **THEN** the check does not report it

### Requirement: Environment inputs are path patterns

Each entry of `environment.inputs.dependencies`, `lock` and `other` SHALL be a path pattern relative to the
repository, where `**` matches any number of directories, and a literal path SHALL be a pattern that matches
itself. The hash SHALL cover every pattern as written, the sorted matched files and their contents. A pattern
that matches no file SHALL be recorded as missing as a missing literal path is, and `abk doctor` SHALL report
it. Matching SHALL exclude `.git` and anything under a path matched by `environment.artifacts`. A pattern that
is absolute or leaves the repository SHALL be a configuration error.

#### Scenario: A manifest in a nested module

- **GIVEN** an input pattern `**/manifest` and a new module with its own manifest
- **WHEN** a unit adds a dependency there and the tick runs
- **THEN** the hash differs and the sync runs

#### Scenario: A pattern that matches nothing

- **WHEN** an input pattern matches no file
- **THEN** the hash records it as missing, and `abk doctor` reports the pattern

#### Scenario: A literal path keeps its meaning

- **GIVEN** an input that names one file and no wildcard
- **WHEN** the hash is taken
- **THEN** it is the hash a literal path always produced

#### Scenario: Manifests inside a dependency directory

- **GIVEN** the pattern `**/manifest` and an artifact pattern naming a dependency directory holding manifests
- **WHEN** the hash is taken
- **THEN** the files in the dependency directory are not matched

#### Scenario: A dependency change is found through patterns

- **GIVEN** a unit that added a matching file the base lacks, or changed one the base has
- **WHEN** the pipeline asks whether the unit changed the inputs
- **THEN** the answer is yes, and a unit that touched no matched file gets no

#### Scenario: A pattern leaving the repository

- **WHEN** an input pattern is absolute or contains `..`
- **THEN** loading the configuration fails naming the field

### Requirement: Artifacts of the environment are pipeline-owned

A repository's configuration SHALL accept `environment.artifacts`, a list of path patterns of what the
environment's `sync` and `check` produce, empty by default. An untracked or modified path matching one SHALL NOT
hold a unit, SHALL NOT be discarded, SHALL NOT be listed to an agent as a leftover and SHALL NOT be committed,
even when the unit changed a dependency input. Artifacts SHALL NOT be part of the inputs hash. A tracked file
matching an artifact pattern SHALL be treated as ordinary tracked work, and `abk doctor` SHALL warn about the
pattern.

#### Scenario: A dependency directory created by the sync

- **GIVEN** an artifact pattern naming a dependency directory the sync creates, not ignored by the repository
- **WHEN** the next step of the unit asks for the worktree
- **THEN** the unit is not held and the directory is still there

#### Scenario: Artifacts are never committed

- **GIVEN** a unit that changed a dependency input and whose sync produced artifacts
- **WHEN** the pipeline commits the unit's work
- **THEN** no artifact path is in the commit

#### Scenario: Other uncommitted files still hold

- **GIVEN** an artifact and an unrelated uncommitted file
- **WHEN** the next step asks for the worktree
- **THEN** the unit is held with the cause `dirty_worktree`, naming only the unrelated file

#### Scenario: Artifacts do not change the hash

- **WHEN** the sync fills an artifact directory
- **THEN** the inputs hash taken afterwards equals the one taken before

#### Scenario: A tracked file under an artifact pattern

- **GIVEN** a tracked file matching an artifact pattern
- **WHEN** it is modified and the unit is committed
- **THEN** it is treated as ordinary work, and `abk doctor` warns that the pattern covers tracked files

#### Scenario: A repository without artifacts

- **WHEN** a repository declares no artifacts
- **THEN** its worktree handling is as before

### Requirement: Each toolchain profile may draft the environment

The toolchain profile SHALL offer an optional hook that, given a repository root, returns a proposed
environment section or None when it cannot say, and a profile without the hook SHALL count as returning None.
`abk init` SHALL ask the profile its detection chose for the repository first and then each other registered
profile in registration order, and SHALL use the first proposal; when none is given it SHALL write empty
commands as it does where nothing is recognised. Init SHALL hold no knowledge of a package manager. For a Python
repository without path sources the section written SHALL be what it was before this requirement, and for one with path sources it SHALL be the drift-checked section of the next requirement. A node profile SHALL propose the
section for a repository with a `package.json` from its lock file, or from the manifest's declared manager when
it names one.

#### Scenario: A Python repository is written as before

- **GIVEN** a repository with a Python manifest and its lock file and no path source
- **WHEN** `abk init` runs
- **THEN** the environment section is identical to the one written before profiles drafted it

#### Scenario: A node repository

- **GIVEN** a repository with `package.json` and a lock file of one manager
- **WHEN** `abk init` runs
- **THEN** the section names that manager's sync and check, the manifest and lock as inputs and the
  dependency directory as an artifact

#### Scenario: A repository with a declared manager

- **GIVEN** a `package.json` that names a manager and a lock file of another
- **WHEN** `abk init` runs
- **THEN** the declared manager is used

#### Scenario: A mixed repository

- **GIVEN** a Python manifest at the root and a node manifest in a subfolder
- **WHEN** `abk init` runs
- **THEN** the profile detection chose is asked first and its proposal is used

#### Scenario: Nothing is recognised

- **WHEN** no registered profile proposes a section
- **THEN** empty commands are written and init says to set them

#### Scenario: A new ecosystem

- **WHEN** a profile that supplies the hook is registered
- **THEN** init proposes its section without any change to init

### Requirement: A drafted environment never lists a path outside the repository

A profile's drafted environment SHALL NOT put in `inputs` any path that leaves the repository, and the draft
SHALL load through the configuration's own validation with no deprecation warning. Where the repository's
manifest takes dependencies from checkouts outside it, the draft SHALL make `check` a drift check: the profile's
own lock-freshness command, then its environment-freshness command, then, where the pipeline runs from this
environment, the check that loads the framework, joined into one argv that fails at the first that fails. The
inputs SHALL hold only the repository's own manifest and lock. The draft SHALL carry a comment saying why. A
manifest without such sources SHALL be drafted as it was, and a profile of another ecosystem SHALL be
unaffected. The warning for a path that leaves the repository SHALL name this remedy: use `check` to detect
drift.

#### Scenario: A manifest with a path source

- **GIVEN** a repository whose manifest names a checkout beside the repository as a source
- **WHEN** `abk init` runs
- **THEN** no input leaves the repository, the inputs hold the repository's own manifest and lock, and the
  draft loads with no deprecation warning

#### Scenario: The check is a drift check

- **GIVEN** the same repository
- **WHEN** the check is read
- **THEN** it differs from the plain import check and runs the lock-freshness command, the
  environment-freshness command and the import check in that order

#### Scenario: Another ecosystem's profile

- **GIVEN** a node-shaped profile that drafts an environment
- **WHEN** `abk init` runs
- **THEN** its draft is unchanged by this requirement

#### Scenario: A repository without path sources

- **WHEN** `abk init` runs over a Python repository whose manifest has no path source
- **THEN** the section is identical to the pinned one

#### Scenario: The warning names the remedy

- **WHEN** a configuration lists an input that leaves the repository
- **THEN** the warning says to use `check` to detect drift

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

- **GIVEN** a repository with no environment section whose unit-test commands create a file its profile names
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
