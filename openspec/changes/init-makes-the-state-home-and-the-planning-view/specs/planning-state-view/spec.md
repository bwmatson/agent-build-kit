## ADDED Requirements

### Requirement: abk init makes the state home and the planning view

In the in-repo mode, `abk init` SHALL create the planning home's state directory and a symbolic link `.planning` in the planning root that points at it with an absolute target, and SHALL add the link's path to the repository's local `info/exclude` so it is never tracked. It SHALL be idempotent, SHALL repoint a dangling link, and SHALL refuse, before changing anything, to replace a regular file, a directory or a link to another existing path named `.planning`, naming it. `--dry-run` SHALL write nothing. In a separate planning repo `abk init` SHALL NOT create the link.

#### Scenario: A first init creates both

- **GIVEN** an in-repo planning root with no `.planning`
- **WHEN** `abk init` runs
- **THEN** the state directory exists, `.planning` is a symbolic link to it, `git status --porcelain` is empty, and `info/exclude` holds the link's line once

#### Scenario: A second init changes nothing, a dangling link is repaired

- **GIVEN** an init that has run, and then a `.planning` link whose target was removed or pointed elsewhere
- **WHEN** `abk init` runs again
- **THEN** the first run reports `unchanged`, the second repoints the link, and `info/exclude` still holds its line once

#### Scenario: A real directory is never replaced

- **GIVEN** a directory named `.planning` holding a file
- **WHEN** `abk init` runs
- **THEN** it exits 1 naming `.planning`, and the directory, its file, the state directory and `info/exclude` are as before

#### Scenario: install-timers does not create it

- **GIVEN** an in-repo installation with no `.planning`
- **WHEN** `abk install-timers` runs
- **THEN** no `.planning` is created and a note names `abk init`

### Requirement: abk doctor reports the planning view

In the working copy and pipeline worktree roles, `abk doctor` SHALL warn when the working copy's `.planning` link is missing, dangling or points elsewhere, naming the problem and `abk init` as the repair, and SHALL report ok when it is right. It SHALL report nothing in a separate planning repo.

#### Scenario: Each state of the link

- **GIVEN** in-repo installations with a right link, no link, a dangling link and a link to another directory
- **WHEN** `abk doctor` runs
- **THEN** the checks are ok, warn, warn and warn, each warning carrying `abk init`

#### Scenario: A separate planning repo is silent

- **GIVEN** a separate planning repo with `runs/` and no `.planning`
- **WHEN** `abk doctor` runs
- **THEN** no check is named `planning view`

### Requirement: State inside the repository is warned about and refused unattended

When the effective state directory (`planning.state_dir`, `ABK_STATE_DIR` or the default), resolved through symbolic links, is the repository's working tree, git directory or inside either, `abk init` and `abk doctor` SHALL warn that state inside the repository dirties the pipeline worktree and stops its fast-forward sync. `abk init --yes` SHALL refuse with exit code 1 naming `--allow-state-in-repo` unless that flag is given; interactively it SHALL ask. A state directory outside the repository, and a separate planning repo's `runs/`, SHALL NOT be warned about.

#### Scenario: Inside the working tree

- **GIVEN** `planning.state_dir` is a path under the repository root
- **WHEN** `abk init --yes` runs
- **THEN** it exits 1 naming `--allow-state-in-repo`, and with the flag it warns and proceeds

#### Scenario: Under the git directory

- **GIVEN** `ABK_STATE_DIR` is a path under `.git`
- **WHEN** `abk doctor` runs
- **THEN** it warns with the setting named and the repair

#### Scenario: A link into the repository

- **GIVEN** a state path outside the repository that is a symbolic link to a folder inside it
- **WHEN** `abk doctor` runs
- **THEN** it warns, naming the resolved path

#### Scenario: Outside, and the legacy mode

- **GIVEN** a state directory outside the repository; and a separate planning repo with `runs/`
- **WHEN** `abk init --yes` and `abk doctor` run
- **THEN** neither warns and init does not refuse
