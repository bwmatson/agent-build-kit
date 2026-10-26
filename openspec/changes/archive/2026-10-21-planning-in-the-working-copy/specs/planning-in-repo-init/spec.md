## ADDED Requirements

### Requirement: `abk init` recognises a repository that is its own planning repo

When `abk init` is given a planning directory and a `--repo` path in the same repository, it SHALL run in in-repo mode with no further flag: the repo's path in the drafted `abk.yaml` is `.`,
an existing `runs/units.json` and every other existing file are left byte for byte, `git init` and `openspec init` are skipped where their results exist, and the files
written are listed. A planning directory that is not in a listed repo SHALL be handled as before.

#### Scenario: An existing store

- **GIVEN** a repository holding `runs/units.json` with units and no `abk.yaml`
- **WHEN** `abk init . --repo .` runs
- **THEN** `abk.yaml` is written with the repo at `.`, and `runs/units.json` is byte for byte what it was

#### Scenario: Run twice

- **GIVEN** the result of the first run
- **WHEN** it runs again
- **THEN** it writes nothing and says so

#### Scenario: A separate directory

- **GIVEN** a planning directory outside the repo
- **WHEN** `abk init <dir> --repo <repo>` runs
- **THEN** the files, the commit and the output are as before

### Requirement: The state directory's ignore lines are added once

In in-repo mode, init SHALL add the template's state-directory ignore lines missing from the repo's `.gitignore` as one marker-bracketed block, once; a line already present anywhere in the file
SHALL NOT be repeated, a block already there SHALL be refreshed in place, and nothing else in the file SHALL change.

#### Scenario: The lines are missing

- **GIVEN** a `.gitignore` without `runs/*.lock`, `runs/locks/`, `runs/unit-logs/`, the ledger, decisions, calls lines and `*.pre-redact`
- **WHEN** init runs
- **THEN** one block holds exactly those lines and the rest of the file is unchanged

#### Scenario: Some are present

- **GIVEN** a `.gitignore` already holding `runs/unit-logs/`
- **WHEN** init runs
- **THEN** the block does not repeat it

#### Scenario: Again

- **GIVEN** the block present
- **WHEN** init runs again
- **THEN** the file is byte for byte unchanged

### Requirement: The planning orientation is added to the repo's own guidance file

In in-repo mode, init SHALL add a marker-bracketed planning orientation (where the specs, configuration, state and graph live, that the pipeline builds changes and
that the specs and state are written here) to the repo's `AGENTS.md`, else its `CLAUDE.md`, else a created `AGENTS.md`, leaving the file's own text byte for byte, and refreshing the block in place on a later run.

#### Scenario: An AGENTS.md exists

- **GIVEN** a repo with its own `AGENTS.md`
- **WHEN** init runs
- **THEN** the block is appended and every other byte is unchanged

#### Scenario: Neither file exists

- **GIVEN** a repo with no guidance file
- **WHEN** init runs
- **THEN** `AGENTS.md` is created holding the block

#### Scenario: Refresh

- **GIVEN** an older block
- **WHEN** init runs
- **THEN** the block is replaced in place and the text around it is unchanged

### Requirement: In-repo init commits nothing and installs the skills once

In in-repo mode init SHALL NOT commit, whether or not the tree is clean, and SHALL list what it wrote. The skills SHALL be installed once into the repo's one skills directory,
and `abk install-skills` and `abk doctor` SHALL list each distinct path once.

#### Scenario: A dirty tree

- **GIVEN** a repo with unrelated uncommitted edits
- **WHEN** init runs
- **THEN** it writes its files, commits nothing, and the unrelated edits are untouched

#### Scenario: Skills

- **GIVEN** the root and the repo's checkout being one directory
- **WHEN** `abk install-skills` runs
- **THEN** each skill is written once, and doctor's skills check lists one path

### Requirement: `abk doctor` accepts a repo that is the root

`abk doctor` SHALL treat a repo whose path is the planning root as valid, with no duplicate entry for it, and SHALL report the pipeline marker and worktree: ok when it names an existing worktree of the repository, a warning when it is stale or when
the state directory's ignore lines are missing from `.gitignore`.

#### Scenario: Repo at the root

- **GIVEN** `repos.<name>.path: .`
- **WHEN** `abk doctor` runs in the pipeline worktree
- **THEN** no check fails for the path and the repo is listed once

#### Scenario: Missing ignore lines

- **GIVEN** an in-repo installation whose `.gitignore` lacks the state lines
- **WHEN** `abk doctor` runs
- **THEN** a warning names `abk init` as the fix

### Requirement: The specs directory is read from the configuration

The tests-first stack runner's change path and init's lookup of an existing change SHALL use `planning.specs_dir`, not the literal `openspec`.

#### Scenario: A specs directory with another name

- **GIVEN** `planning.specs_dir: specs`
- **WHEN** the stack runner names the change directory and init looks for an existing change
- **THEN** both use `specs/changes/<change>`
